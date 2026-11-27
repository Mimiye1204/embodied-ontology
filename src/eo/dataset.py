# -*- coding: utf-8 -*-
"""带语义标签的数据集生成（本体导入 + 故障注入 + 规则推理 → 标注样本）。

每个 (任务 × 故障场景) 产出一条样本，样本用本体术语标注（IRI + 中文标签）：
  task / object / robot / required_capabilities / 故障模式 / 部件健康
  / 失效能力（故障传播）/ 可达性 verdict / 是否受影响 / 动作拦截维度

- baseline = 干净世界（全部部件 ok、全部故障事件 resolved）
- 故障场景 = 在干净世界上注入该模式（受影响部件 health=fault）

直接可喂给 ML（如任务可行性预测：给定故障状态 → verdict）。
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional

from .graph import MemoryStore
from .graph.loader import load_entities
from .reasoning import trace_root_cause
from .rules import DOMAIN_RULES, FAULT_RULES, check_reachability, intercept_action
from .rules.framework import RuleEngine
from .shacl import validate_entities


def _build_store(entities: List[Dict[str, Any]], mode: Optional[Dict[str, Any]]):
    """构造一个场景的世界图：干净副本（部件 ok + 事件 resolved），注入 mode 则部件 fault。

    用 load_entities（快，不做 SHACL）——输入已整体校验过，健康=fault 是合法枚举值。
    """
    ents = copy.deepcopy(entities)
    for e in ents:
        if e["type"] == "BodyPart":
            e["health"] = "ok"
        elif e["type"] == "FaultEvent":
            e["status"] = "resolved"
    if mode is not None:
        affected = set(mode.get("affects_bodypart", []))
        for e in ents:
            if e["id"] in affected:
                e["health"] = "fault"
    store = MemoryStore()
    load_entities(store, ents)
    return store


def generate_labeled_dataset(
    entities: List[Dict[str, Any]],
    fault_modes: Optional[List[str]] = None,
    task_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """生成语义标注样本集。

    - 场景 = baseline（无故障）+ 每个故障模式（fault_modes 为空则取本体里全部 FaultMode）
    """
    ok, report = validate_entities(entities)   # 整体校验一次，逐样本不再重校验
    if not ok:
        raise ValueError(f"输入本体未过 Gate A：{report.violations[0].message if report.violations else report}")

    tasks = sorted([e for e in entities if e["type"] == "Task"
                    and (task_ids is None or e["id"] in task_ids)], key=lambda e: e["id"])
    modes = sorted([e for e in entities if e["type"] == "FaultMode"
                    and (fault_modes is None or e["id"] in fault_modes)], key=lambda e: e["id"])

    samples: List[Dict[str, Any]] = []
    for task in tasks:
        obj_id = task.get("involves_object")
        obj = next((e for e in entities if e["id"] == obj_id), None)

        for scenario_id, scenario_label, mode in ([("baseline", "无故障", None)]
                                                  + [(m["id"], m.get("label", m["id"]), m) for m in modes]):
            store = _build_store(entities, mode)

            eng = RuleEngine(store)
            eng.add_rules(DOMAIN_RULES + FAULT_RULES)
            eng.run()

            r = check_reachability(store, task["id"])
            hits = intercept_action(store, task["id"])
            lost = sorted(f.s for f in eng.facts.values() if f.p == "lost")
            affected = eng.facts.get((task["id"], "affected_by_fault")) is not None
            health = {n.id: n.get("health", "ok") for n in store.nodes()
                      if n.type == "BodyPart"}
            root_causes = [c.entity for c in trace_root_cause(store, task["id"]).causes]

            samples.append({
                "id": f"{task['id']}|{scenario_id}",
                "task": task["id"],
                "task_label": task.get("label", ""),
                "object": obj_id,
                "object_label": obj.get("label", "") if obj else None,
                "robot": task.get("assigned_to"),
                "required_capabilities": list(task.get("requires_capability", [])),
                "scenario": scenario_id,
                "scenario_label": scenario_label,
                "health": health,
                "lost_capabilities": lost,
                "verdict": r.verdict,
                "affected": affected,
                "root_causes": root_causes,
                "interceptions": [h.kind for h in hits],
                "interception_rewrites": [h.rewrite for h in hits],
            })
    return samples


def export_dataset(samples: List[Dict[str, Any]], path: Optional[str] = None,
                   format: str = "json") -> str:
    """导出样本集。format=json（列表）或 jsonl（每行一条）。返回序列化文本。"""
    if format == "jsonl":
        text = "\n".join(json.dumps(s, ensure_ascii=False) for s in samples)
    else:
        text = json.dumps(samples, ensure_ascii=False, indent=2)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + ("\n" if format == "jsonl" else ""))
    return text
