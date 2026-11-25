# -*- coding: utf-8 -*-
"""规则执行结果单元测试：演绎/约束/归纳的精确断言 + 证明链 + 动作绑定 + 推理 API。"""
from __future__ import annotations

from eo.actions import build_registry
from eo.crud import OntologyCRUD
from eo.rules import (
    check_reachability, intercept_action, intercept_report,
    propagate_fault, propagate_fault_event, root_cause,
)
from eo.rules.framework import RuleContext, RuleEngine, RuleSpec


class TestDeduction:
    def test_handle_implies_graspable(self, engine):
        graspable = {f.s for f in engine.facts.values() if f.p == "graspable"}
        assert graspable == {"eo:object/cup", "eo:object/cup-slip",
                             "eo:object/kettle", "eo:object/door"}

    def test_fragile_implies_force_control(self, engine):
        assert ("eo:object/egg", "needs_force_control") in engine.facts

    def test_thread_implies_screw(self, engine):
        assert ("eo:object/bottle", "needs_screw") in engine.facts


class TestConstraint:
    def test_torque_exact_values(self, engine):
        assert engine.facts[("eo:task/carry-kettle", "over_torque")].v == 0.6
        assert engine.facts[("eo:task/carry-cup", "torque_ok")].v == 0.09
        assert engine.facts[("eo:task/push-box", "over_torque")].v == 9.0

    def test_load_exact_values(self, engine):
        assert engine.facts[("eo:task/push-box", "over_load")].v == 30.0
        assert engine.facts[("eo:task/open-door", "over_load")].v == 5.0


class TestInduction:
    def test_grip_factor(self, engine):
        assert engine.facts[("eo:object/cup-slip", "grip_factor")].v == 1.5
        assert engine.facts[("eo:object/cup", "grip_factor")].v == 1.0


class TestProofChain:
    def test_explain(self, engine):
        text = engine.explain("eo:task/carry-kettle", "over_torque")
        assert "torque_constraint" in text
        assert "kettle" in text and "力臂" in text

    def test_priority_dedup(self, store):
        eng = RuleEngine(store)

        def low(ctx: RuleContext):
            ctx.assert_(store.nodes()[0].id, "p", "low")

        def high(ctx: RuleContext):
            ctx.assert_(store.nodes()[0].id, "p", "high")

        eng.add_rule(RuleSpec("low", "", priority=10, fire=low))
        eng.add_rule(RuleSpec("high", "", priority=999, fire=high))
        eng.run()
        assert eng.facts[(store.nodes()[0].id, "p")].v == "high"


class TestRuleActionBinding:
    def test_monitor_rule_triggers_writeback(self, crud):
        reg = build_registry(crud)
        eng = RuleEngine(crud.store, actions=reg)

        def monitor(ctx: RuleContext):
            ctx.assert_("eo:object/cup", "slip", True, evidence=["测试"])

        eng.add_rule(RuleSpec(
            "slip_monitor", "", category="monitoring", priority=50, fire=monitor,
            actions=[{"action": "knowledge.writeback",
                      "params": {"entity_id": "{s}", "patch": {"surface": "slippery"}}}],
        ))
        eng.run()
        assert crud.get("eo:object/cup")["surface"] == "slippery"
        assert any("eo:log/action-" in eid for eid in crud.entities)


class TestReachability:
    def test_verdicts(self, store):
        assert check_reachability(store, "eo:task/grasp-egg").verdict == "feasible"
        assert check_reachability(store, "eo:task/carry-cup").verdict == "feasible"
        assert check_reachability(store, "eo:task/sit-down").verdict == "feasible"


class TestFaultPropagation:
    def test_event_propagation(self, store):
        impact = propagate_fault_event(store, "eo:event/fault-001")
        assert impact.faulty_parts == ["eo:part/ti5/six-axis-force"]
        assert impact.lost_capabilities == ["eo:cap/force-control"]
        assert set(impact.affected_tasks) == {"eo:task/grasp-egg", "eo:task/pinch-coin"}

    def test_direct_propagation_and_root_cause(self, mutable_store):
        impact = propagate_fault(mutable_store, "eo:part/ti5/dexterous-hand")
        assert "eo:cap/power-grasp" in impact.lost_capabilities
        mutable_store.get_node("eo:part/ti5/six-axis-force").properties["health"] = "fault"
        assert root_cause(mutable_store, "eo:task/grasp-egg") == ["eo:part/ti5/six-axis-force"]


class TestInterception:
    def test_torque_container_rewrite(self, store):
        hits = intercept_action(store, "eo:task/carry-kettle")
        assert [h.kind for h in hits] == ["torque"]
        assert "倒水" in hits[0].rewrite

    def test_push_box_three_dimensions(self, store):
        kinds = {h.kind for h in intercept_action(store, "eo:task/push-box")}
        assert {"torque", "load", "gripper"} <= kinds

    def test_pose_and_surface(self, store):
        pose = next(h for h in intercept_action(store, "eo:task/sit-down") if h.kind == "pose")
        assert "改写任务意义" in pose.rewrite
        surf = next(h for h in intercept_action(store, "eo:task/carry-slip-cup") if h.kind == "surface")
        assert "1.5" in surf.rewrite

    def test_report_structure(self, store):
        report = intercept_report(store, "eo:task/push-box")
        assert not report.allowed and report.interceptions
        assert len(report.rewrites) == len(report.interceptions)
        assert intercept_report(store, "eo:task/carry-cup").allowed
