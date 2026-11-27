# -*- coding: utf-8 -*-
"""图推理接口（依赖闭包 / 正向影响面 / 反向根因溯源）单元测试。"""
from __future__ import annotations

import json
from pathlib import Path

from eo.reasoning import dependency_closure, fault_impact, trace_root_cause

ROOT = Path(__file__).resolve().parent.parent


def _world_store():
    from eo.graph import MemoryStore
    from eo.graph.loader import load_entities
    fleet = json.loads((ROOT / "examples" / "fleet.json").read_text(encoding="utf-8"))
    faults = json.loads((ROOT / "examples" / "faults.json").read_text(encoding="utf-8"))
    store = MemoryStore()
    load_entities(store, fleet + faults)
    return store


class TestDependencyClosure:
    def test_closure(self):
        store = _world_store()
        d = dependency_closure(store, "eo:task/grasp-egg")
        assert set(d.capabilities) == {"eo:cap/power-grasp", "eo:cap/force-control"}
        assert set(d.parts) == {"eo:part/ti5/dexterous-hand", "eo:part/ti5/six-axis-force"}
        assert d.robot == "eo:robot/ti5"
        assert "eo:constraint/grip-force-limit" in d.constraints  # 约束灵巧手


class TestFaultImpact:
    def test_part_impact(self):
        store = _world_store()
        impact = fault_impact(store, "eo:part/ti5/dexterous-hand")
        assert set(impact.lost_capabilities) == {"eo:cap/power-grasp", "eo:cap/pinch", "eo:cap/press"}

    def test_event_impact(self):
        store = _world_store()
        impact = fault_impact(store, "eo:event/fault-001")
        assert impact.lost_capabilities == ["eo:cap/force-control"]
        assert set(impact.affected_tasks) == {"eo:task/grasp-egg", "eo:task/pinch-coin"}


class TestRootCause:
    def test_part_fault_root_cause(self, mutable_store):
        mutable_store.get_node("eo:part/ti5/six-axis-force").properties["health"] = "fault"
        report = trace_root_cause(mutable_store, "eo:task/grasp-egg")
        parts = [c.entity for c in report.causes if c.entity_type == "BodyPart"]
        assert "eo:part/ti5/six-axis-force" in parts
        # 证据链：症状 → 能力 → 提供者
        cause = next(c for c in report.causes if c.entity == "eo:part/ti5/six-axis-force")
        assert any("force-control" in ev for ev in cause.evidence)

    def test_event_root_cause(self):
        store = _world_store()   # faults.json 含活跃事件 fault-002（hand-motor）
        report = trace_root_cause(store, "eo:task/carry-cup")
        events = [c for c in report.causes if c.entity_type == "FaultEvent"]
        assert events, "carry-cup 依赖 power-grasp，应有活跃事件根因"
        assert any("fault-002" in c.entity for c in events)

    def test_capability_symptom(self, mutable_store):
        mutable_store.get_node("eo:part/ti5/dexterous-hand").properties["health"] = "degraded"
        report = trace_root_cause(mutable_store, "eo:cap/power-grasp")
        assert any(c.entity_type == "BodyPart" and c.entity == "eo:part/ti5/dexterous-hand"
                   for c in report.causes)

    def test_healthy_no_root_cause(self, mutable_store):
        # 干净世界（无故障）→ 无根因
        report = trace_root_cause(mutable_store, "eo:task/sit-down")
        assert report.causes == []
