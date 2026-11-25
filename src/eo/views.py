# -*- coding: utf-8 -*-
"""本体能力视图：从本体图投影出给调度中台的契约对象（docs/05）。

- build_capability_view：每台机器人 → 能力清单（健康判定）/ 适用约束 / 活跃故障；
  全局测点注册表。全部从本体图派生（复用 part_of_robot 部件归属）。
- 输出两种形态：
  1) 纯 JSON（平台契约，对应 schema/capability_view.yaml 生成的 JSON Schema）
  2) JSON-LD（带 @context + 类型注入，语义自描述）
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .graph.base import GraphStore
from .jsonld.context import build_context
from .rules.reachability import part_of_robot
from .schema import schema_view

VIEW_SCHEMA = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "schema", "capability_view.yaml"))
ONTOLOGY_VERSION = "1.1.0"

# JSON-LD 类型注入：嵌套对象在 JSON-LD 里需要 @type
_NESTED_TYPE = {
    "robots": "RobotCapability",
    "capabilities": "CapabilityEntry",
    "constraints": "ConstraintEntry",
    "active_faults": "FaultEntry",
    "metrics": "MetricEntry",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_capability_view(
    store: GraphStore,
    robot_id: Optional[str] = None,
    ontology_version: str = ONTOLOGY_VERSION,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """投影本体图 → 能力视图（根文档 dict）。robot_id 给定时只含该机器人。"""
    robots = [n for n in store.nodes()
              if n.type == "Robot" and (robot_id is None or n.id == robot_id)]
    robot_entries: List[Dict[str, Any]] = []

    for r in sorted(robots, key=lambda n: n.id):
        parts = [p for p in store.nodes()
                 if p.type == "BodyPart" and part_of_robot(store, p.id, r.id)]
        part_ids = {p.id for p in parts}

        # 能力：部件提供的全部能力（合并多部件提供同一能力）
        caps: Dict[str, Dict[str, Any]] = {}
        for p in parts:
            for cap in store.out_neighbors(p.id, "provides_capability"):
                caps.setdefault(cap.id, {
                    "code": cap.get("code", ""), "label": cap.get("label", ""), "parts": [],
                })
                caps[cap.id]["parts"].append(p.id)
        cap_entries = []
        for c in caps.values():
            healths = [store.get_node(pid).get("health", "ok") for pid in c["parts"]
                       if store.get_node(pid)]
            cap_entries.append({
                "code": c["code"], "label": c["label"],
                "part_ids": sorted(c["parts"]),
                "healthy": all(h == "ok" for h in healths),
                "degraded": any(h == "degraded" for h in healths),
            })

        # 约束：作用于该机器人的部件或机器人本身
        con_entries = []
        for con in store.nodes():
            if con.type != "Constraint":
                continue
            if any(t.id in part_ids or t.id == r.id
                   for t in store.out_neighbors(con.id, "constrains")):
                con_entries.append({
                    "code": con.id,
                    "constraint_type": con.get("constraint_type", ""),
                    "expression": con.get("expression", ""),
                    "threshold": con.get("threshold"),
                    "unit": con.get("unit", ""),
                })

        # 活跃故障：影响该机器人部件的未解决事件
        fault_entries = []
        for f in store.nodes():
            if f.type != "FaultEvent" or f.get("status") != "active":
                continue
            if any(t.id in part_ids for t in store.out_neighbors(f.id, "affects_bodypart")):
                mode = store.out_neighbors(f.id, "of_mode")
                fault_entries.append({
                    "event_id": f.id,
                    "mode_code": mode[0].get("mode_code") if mode else None,
                    "severity": f.get("severity", ""),
                    "status": f.get("status", ""),
                    "detected_at": f.get("detected_at"),
                })

        robot_entries.append({
            "id": r.id, "serial": r.get("serial", ""), "model": r.get("model", ""),
            "status": r.get("status", ""),
            "capabilities": sorted(cap_entries, key=lambda e: e["code"]),
            "constraints": con_entries,
            "active_faults": fault_entries,
        })

    metrics = []
    for m in store.nodes():
        if m.type != "TelemetryMetric":
            continue
        targets = store.out_neighbors(m.id, "measures")
        metrics.append({
            "metric_code": m.get("metric_code", ""),
            "measures_entity": targets[0].id if targets else None,
            "binds_to": m.get("binds_to"),
            "unit": m.get("unit"),
            "value_type": m.get("value_type"),
            "aggregation": m.get("aggregation"),
        })

    return {
        "id": "cv:view/capability",
        "generated_at": generated_at or _now_iso(),
        "ontology_version": ontology_version,
        "robots": robot_entries,
        "metrics": sorted(metrics, key=lambda e: e["metric_code"]),
    }


def _inject_types(node: Any, key: Optional[str] = None) -> Any:
    """JSON-LD 需要嵌套对象带 @type；按 key 注入 type。"""
    if isinstance(node, dict):
        out = dict(node)
        if key in _NESTED_TYPE:
            out["type"] = _NESTED_TYPE[key]
        for k, v in out.items():
            if isinstance(v, (dict, list)):
                out[k] = _inject_types(v, k)
        return out
    if isinstance(node, list):
        return [_inject_types(x, key) for x in node]
    return node


def view_as_jsonld(view: Dict[str, Any]) -> Dict[str, Any]:
    """能力视图 → JSON-LD 文档（@context 由能力视图 Schema 推导 + 类型注入）。"""
    sv = schema_view(VIEW_SCHEMA)
    typed = _inject_types(view, None)
    typed["type"] = "CapabilityView"
    return {"@context": build_context(sv), "@graph": [typed]}
