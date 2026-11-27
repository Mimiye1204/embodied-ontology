# -*- coding: utf-8 -*-
"""故障链路（fault links）单元测试：模式库传播 / 冗余 / 根因 / 动作注入 / 图遍历。"""
from __future__ import annotations

from eo.actions import build_registry
from eo.graph.traversal import resolve
from eo.rules import check_reachability, propagate_fault, root_cause


class TestFaultLinks:
    def test_part_fault_loses_capabilities(self, store):
        """灵巧手故障 → power-grasp/pinch/press 三能力失效 → 相关任务受影响。"""
        impact = propagate_fault(store, "eo:part/ti5/dexterous-hand")
        assert set(impact.lost_capabilities) == {"eo:cap/power-grasp", "eo:cap/pinch", "eo:cap/press"}
        assert set(impact.affected_tasks) >= {
            "eo:task/carry-cup", "eo:task/pinch-coin", "eo:task/press-button", "eo:task/grasp-egg",
        }

    def test_fault_redundancy(self, mutable_store):
        """push 由 base + arm 双部件提供：arm 故障后 push 仍由 base 提供 → 推箱子仍可达。"""
        mutable_store.get_node("eo:part/ti5/arm").properties["health"] = "fault"
        r = check_reachability(mutable_store, "eo:task/push-box")
        assert r.verdict == "feasible"
        # 依赖隔离：依赖 arm 的倒水则不可达
        assert check_reachability(mutable_store, "eo:task/pour-water").verdict == "infeasible"

    def test_root_cause(self, mutable_store):
        mutable_store.get_node("eo:part/ti5/six-axis-force").properties["health"] = "fault"
        assert root_cause(mutable_store, "eo:task/grasp-egg") == ["eo:part/ti5/six-axis-force"]

    def test_fault_chain_traversal(self, store):
        """用图遍历沿依赖链：事件 → 模式 → 失效能力 ← 受影响任务。"""
        tasks = resolve(store, "eo:event/fault-001", [
            ("out", "of_mode"),
            ("out", "affects_capability"),
            ("in", "requires_capability"),
        ])
        assert set(tasks) == {"eo:task/grasp-egg", "eo:task/pinch-coin"}


class TestFaultAction:
    def test_fault_report_action(self, crud):
        """fault.report 动作：建事件 + 部件置 fault + 传播消息。"""
        reg = build_registry(crud)
        result = reg.execute("fault.report", actor="test",
                             mode_id="eo:faultmode/hand-motor-failure")
        assert result.ok and result.audit_log_id
        assert crud.get("eo:part/ti5/dexterous-hand")["health"] == "fault"
        assert any("受影响任务" in m for m in result.messages)

    def test_fault_report_unknown_mode(self, crud):
        reg = build_registry(crud)
        result = reg.execute("fault.report", actor="test", mode_id="eo:faultmode/ghost")
        assert not result.ok
