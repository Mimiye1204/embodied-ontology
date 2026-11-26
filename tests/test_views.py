# -*- coding: utf-8 -*-
"""能力视图 + JSON-LD 过滤导出 单元测试（输出给调度中台的契约）。"""
from __future__ import annotations

from eo.jsonld import export_jsonld
from eo.views import build_capability_view, view_as_jsonld


class TestCapabilityView:
    def test_root_structure(self, store):
        view = build_capability_view(store)
        assert view["id"] == "cv:view/capability"
        assert view["ontology_version"] == "1.1.0"
        assert "generated_at" in view
        assert {r["id"] for r in view["robots"]} == {"eo:robot/ti5"}

    def test_robot_capability_footprint(self, store):
        view = build_capability_view(store, robot_id="eo:robot/ti5")
        assert len(view["robots"]) == 1
        robot = view["robots"][0]
        caps = {c["code"]: c for c in robot["capabilities"]}
        assert "power-grasp" in caps
        assert caps["power-grasp"]["healthy"] is True
        assert "eo:part/ti5/dexterous-hand" in caps["power-grasp"]["part_ids"]
        # 约束已纳入（作用在 ti5 腕部）
        assert any(c["constraint_type"] == "torque" for c in robot["constraints"])

    def test_metrics_registry(self, store):
        view = build_capability_view(store)
        codes = {m["metric_code"] for m in view["metrics"]}
        assert {"force_reading", "battery", "joint_angle", "task_progress"} <= codes
        battery = next(m for m in view["metrics"] if m["metric_code"] == "battery")
        assert battery["binds_to"] == "current_battery"

    def test_view_reflects_fault(self, mutable_store):
        mutable_store.get_node("eo:part/ti5/six-axis-force").properties["health"] = "fault"
        view = build_capability_view(mutable_store, robot_id="eo:robot/ti5")
        caps = {c["code"]: c for c in view["robots"][0]["capabilities"]}
        assert caps["force-control"]["healthy"] is False
        assert caps["power-grasp"]["healthy"] is True  # 依赖隔离

    def test_active_fault_entry(self, store):
        view = build_capability_view(store, robot_id="eo:robot/ti5")
        faults = view["robots"][0]["active_faults"]
        assert any(f["event_id"] == "eo:event/fault-001" for f in faults)
        f = next(f for f in faults if f["event_id"] == "eo:event/fault-001")
        assert f["mode_code"] == "force-sensor-failure"


class TestViewJsonld:
    def test_jsonld_form(self, store):
        doc = view_as_jsonld(build_capability_view(store))
        assert "@context" in doc and "@graph" in doc
        root = doc["@graph"][0]
        assert root["type"] == "CapabilityView"
        assert root["robots"][0]["type"] == "RobotCapability"
        assert root["robots"][0]["capabilities"][0]["type"] == "CapabilityEntry"


class TestFilteredExport:
    def test_export_by_type(self, store):
        doc = export_jsonld(store, types=["Robot"])
        assert {e["type"] for e in doc["@graph"]} == {"Robot"}
        assert len(doc["@graph"]) == 1  # 仅 ti5

    def test_export_by_id_includes_references(self, store):
        doc = export_jsonld(store, ids=["eo:task/grasp-egg"])
        ids = {e["id"] for e in doc["@graph"]}
        assert "eo:task/grasp-egg" in ids
        # 直接引用（一跳）：涉及的能力/物体/指派机器人一并带出
        assert "eo:cap/power-grasp" in ids and "eo:cap/force-control" in ids
        assert "eo:object/egg" in ids
        assert "eo:robot/ti5" in ids
        # 非直接引用（ti5 自己的 located_at）不越界带出
        assert "eo:site/hq" not in ids
