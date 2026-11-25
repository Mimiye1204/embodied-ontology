# -*- coding: utf-8 -*-
"""本体底座整体自检：Schema → 对象 → 链路 → 规则 → 动作 → 写路径 → 导出 → 能力视图 联调。

核心价值在**跨层一致性**：
  - 对象层：数据清单实体数 == 图节点数
  - 链路层：数据清单 Link 槽目标数 == 图边数（无悬空）
  - 规则层：关键事实精确值（over_torque=0.6 / grip_factor=1.5）
  - 动作层：dispatch 写回 verdict/status 且经 Gate A 再校验
  - 写路径：create/update/delete 贯穿 图 ↔ JSON-LD 导出 ↔ 能力视图
  - 导出层：JSON-LD round-trip 无损；能力视图能力集合 == 图能力集合

run_selfcheck() 返回检查结果列表；print_report() 打印人类可读报告并返回失败数。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .actions import build_registry
from .crud import OntologyCRUD
from .jsonld import export_jsonld, from_jsonld_document
from .rules import DOMAIN_RULES, check_reachability
from .rules.framework import RuleEngine
from .schema import all_classes, all_slots, schema_view
from .shacl import validate_entities
from .views import build_capability_view

_ONTOLOGY_VERSION = "1.1.0"


@dataclass
class Check:
    name: str
    passed: bool = False
    detail: str = ""
    checks: List[bool] = field(default_factory=list)   # 内部子断言

    def sub(self, ok: bool, msg: str) -> None:
        self.checks.append(ok)
        if not ok:
            self.detail += (self.detail and "；" or "") + msg


def _edge_count_of(entities: List[Dict[str, Any]]) -> int:
    """数据清单里 Link 槽的目标总数 = 期望边数。"""
    from .schema import link_slots
    n = 0
    for e in entities:
        for slot in link_slots(e["type"]):
            v = e.get(slot)
            if v is None:
                continue
            n += len(v) if isinstance(v, list) else 1
    return n


def run_selfcheck(data_path: str, robot_id: Optional[str] = "eo:robot/ti5") -> List[Check]:
    import json
    import os

    results: List[Check] = []

    with open(data_path, encoding="utf-8") as f:
        entities = json.load(f)

    # ------------------------------------------------------ 1. Schema
    c = Check("[1] Schema 加载")
    try:
        sv = schema_view()
        c.sub(len(all_classes()) == 13, f"ObjectType 应 13，实 {len(all_classes())}")
        c.sub(sv.schema.version == _ONTOLOGY_VERSION, f"版本应 {_ONTOLOGY_VERSION}")
        c.sub(len(all_slots()) >= 76, f"槽数应 ≥76，实 {len(all_slots())}")
        c.detail = f"v{sv.schema.version} · {len(all_classes())} ObjectType · {len(all_slots())} 槽"
    except Exception as e:
        c.detail = f"异常：{e}"
    c.passed = all(c.checks) if c.checks else False
    results.append(c)

    # ------------------------------------------------------ 2. Gate A
    c = Check("[2] Gate A 校验（SHACL L0+L1）")
    ok, report = validate_entities(entities)
    c.sub(ok, report[:120])
    c.detail = f"{len(entities)} 实例" + ("全部合法" if ok else "校验失败")
    c.passed = ok
    results.append(c)

    # ------------------------------------------------------ 3. 对象建图
    crud = OntologyCRUD()
    crud.load(copy.deepcopy(entities))
    c = Check("[3] 对象建图（数据清单 ↔ 图节点）")
    node_count = len(crud.store.nodes())
    c.sub(node_count == len(entities), f"节点数 {node_count} ≠ 清单 {len(entities)}")
    c.sub(all(crud.store.has_node(e["id"]) for e in entities), "存在缺节点")
    c.passed = all(c.checks)
    c.detail = f"{node_count} 节点（清单 {len(entities)}）"
    results.append(c)

    # ------------------------------------------------------ 4. 链路建图
    c = Check("[4] 链路建图（Link 槽 ↔ 图边）")
    edge_count = len(crud.store.edges())
    expected_edges = _edge_count_of(entities)
    c.sub(edge_count == expected_edges, f"边数 {edge_count} ≠ 期望 {expected_edges}")
    c.passed = all(c.checks)
    c.detail = f"{edge_count} 边（期望 {expected_edges}，无悬空）"
    results.append(c)

    # ------------------------------------------------------ 5. 规则执行
    c = Check("[5] 规则执行（关键事实精确值）")
    eng = RuleEngine(crud.store)
    eng.add_rules(DOMAIN_RULES)
    eng.run()
    f = eng.facts
    c.sub(f.get(("eo:task/carry-kettle", "over_torque")) and
          f[("eo:task/carry-kettle", "over_torque")].v == 0.6, "over_torque≠0.6")
    c.sub(f.get(("eo:object/cup-slip", "grip_factor")) and
          f[("eo:object/cup-slip", "grip_factor")].v == 1.5, "grip_factor≠1.5")
    c.sub(f.get(("eo:task/push-box", "over_load")) and
          f[("eo:task/push-box", "over_load")].v == 30.0, "over_load≠30.0")
    c.sub(("eo:object/cup", "graspable") in f, "缺 graspable 演绎事实")
    c.passed = all(c.checks)
    c.detail = f"{len(f)} 事实（关键值 over_torque=0.6 / grip_factor=1.5 / over_load=30.0）"
    results.append(c)

    # ------------------------------------------------------ 6. 动作联调
    c = Check("[6] 动作联调（dispatch 写回 + 审计 + 再校验）")
    reg = build_registry(crud)
    r = reg.execute("task.dispatch", actor="selfcheck", task_id="eo:task/carry-cup")
    task = crud.get("eo:task/carry-cup")
    c.sub(bool(r.ok), "dispatch 动作失败")
    c.sub(task.get("status") == "executing" and task.get("verdict") == "feasible",
          f"写回错误：status={task.get('status')} verdict={task.get('verdict')}")
    c.sub(r.audit_log_id and crud.get(r.audit_log_id) is not None, "审计未落库")
    c.sub(crud.validate().conforms, "写回后 Gate A 校验失败")
    c.passed = all(c.checks)
    c.detail = f"verdict=feasible · status=executing · 审计 {r.audit_log_id}"
    results.append(c)

    # ------------------------------------------------------ 7. 写路径联调
    c = Check("[7] 写路径联调（create→update→delete 贯穿图/导出/视图）")
    c.sub(crud.create({"id": "eo:object/table", "type": "Object", "label": "桌子",
                       "weight_kg": 15.0, "surface": "dry",
                       "created_at": "2026-11-25T10:00:00+08:00"}) is None, "create 抛异常")
    c.sub(crud.get("eo:object/table") is not None, "create 后 get 失败")
    crud.set_property("eo:object/table", "weight_kg", 16.0)
    c.sub(crud.get_property("eo:object/table", "weight_kg") == 16.0, "update 未生效")
    doc = export_jsonld(crud.store)
    c.sub(any(e["id"] == "eo:object/table" for e in doc["@graph"]), "新对象未进 JSON-LD 导出")
    crud.delete("eo:object/table")
    c.sub(crud.get("eo:object/table")["deprecated"] is True, "软删除未生效")
    c.passed = all(c.checks)
    c.detail = "create→update(16.0kg)→soft-delete，导出同步"
    results.append(c)

    # ------------------------------------------------------ 8. JSON-LD round-trip
    c = Check("[8] JSON-LD round-trip")
    doc = export_jsonld(crud.store)
    back = from_jsonld_document(doc)
    ids_orig = {e["id"] for e in crud.entities.values()}
    ids_back = {e["id"] for e in back}
    c.sub(ids_orig == ids_back, f"round-trip 不一致（{len(ids_orig)}≠{len(ids_back)}）")
    c.passed = all(c.checks)
    c.detail = f"{len(doc['@graph'])} 节点 → 导入 {len(back)} 实体，无损"
    results.append(c)

    # ------------------------------------------------------ 9. 能力视图
    c = Check("[9] 能力视图（机器人能力足迹）")
    view = build_capability_view(crud.store)
    robots = view["robots"]
    c.sub(len(robots) == 2, f"机器人应 2，实 {len(robots)}")
    ti5 = next((r for r in robots if r["id"] == "eo:robot/ti5"), None)
    c.sub(ti5 is not None and any(cap["code"] == "power-grasp" for cap in ti5["capabilities"]),
          "ti5 能力足迹缺 power-grasp")
    c.sub(all("healthy" in cap and "degraded" in cap for cap in ti5["capabilities"]),
          "能力缺健康判定字段")
    c.passed = all(c.checks)
    c.detail = f"{len(robots)} 机器人 · ti5 能力 {len(ti5['capabilities']) if ti5 else 0} 项"
    results.append(c)

    # ------------------------------------------------------ 10. 视图 ↔ 本体一致性
    c = Check("[10] 视图 ↔ 本体一致性（能力集合/故障反映）")
    view_caps = {cap["code"] for r in view["robots"] for cap in r["capabilities"]}
    graph_caps = {n.get("code") for n in crud.store.nodes() if n.type == "Capability"}
    c.sub(view_caps == graph_caps, f"能力集合不一致：视图{len(view_caps)}≠图{len(graph_caps)}")
    # 故障注入（干净副本）→ 视图健康反映
    mut = OntologyCRUD()
    mut.load(copy.deepcopy(entities))
    mut.set_property("eo:part/ti5/six-axis-force", "health", "fault")
    vf = build_capability_view(mut.store)
    fcs = {cap["code"]: cap for r in vf["robots"] if r["id"] == "eo:robot/ti5"
           for cap in r["capabilities"]}
    c.sub(fcs.get("force-control", {}).get("healthy") is False, "故障未反映到视图")
    c.sub(fcs.get("power-grasp", {}).get("healthy") is True, "依赖隔离失效")
    c.passed = all(c.checks)
    c.detail = f"视图能力 {len(view_caps)} == 图能力 {len(graph_caps)}；故障依赖隔离正确"
    results.append(c)

    return results


def print_report(results: List[Check]) -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    failed = 0
    print("=" * 72)
    print("具身本体论引擎 · 本体底座整体自检（Schema→对象→链路→规则→导出 联调）")
    print("=" * 72)
    for c in results:
        mark = "✓" if c.passed else "✗"
        print(f"{mark} {c.name}")
        print(f"    {c.detail}")
        failed += 0 if c.passed else 1
    print("-" * 72)
    print(f"结果：{len(results) - failed}/{len(results)} 通过")
    return failed
