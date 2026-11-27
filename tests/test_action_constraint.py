# -*- coding: utf-8 -*-
"""动作约束（action constraints）单元测试：拦截器边界 / 数据驱动 / 下发集成。"""
from __future__ import annotations

from eo.actions import build_registry
from eo.rules import intercept_action, intercept_report


class TestInterceptorBoundary:
    def test_constraint_data_driven(self, crud):
        """抬高力矩阈值 → 原本超限的「端满水壶」不再触发 torque 拦截。"""
        before = {h.kind for h in intercept_action(crud.store, "eo:task/carry-kettle")}
        assert "torque" in before
        crud.set_property("eo:constraint/wrist-torque-limit", "threshold", 1.0)
        after = {h.kind for h in intercept_action(crud.store, "eo:task/carry-kettle")}
        assert "torque" not in after, "约束库阈值应是拦截判定的唯一数值来源"

    def test_gripper_slippery_surface_triggers(self, crud):
        """3kg 物体：干燥 29.4N < 40N 不触发；湿滑 ×1.5 → 44.1N > 40N 触发 gripper。"""
        crud.set_property("eo:object/cup-slip", "weight_kg", 3.0)
        kinds = {h.kind for h in intercept_action(crud.store, "eo:task/carry-slip-cup")}
        assert "gripper" in kinds
        assert "surface" in kinds  # 湿滑本身也触发 surface 拦截

    def test_no_object_no_physical_constraint(self, crud):
        """无涉及物体的任务：不触发 torque/load/gripper/surface。"""
        crud.create({"id": "eo:task/no-object", "type": "Task", "label": "无物体任务",
                     "status": "pending", "requires_capability": ["eo:cap/power-grasp"],
                     "assigned_to": "eo:robot/ti5",
                     "created_at": "2026-11-27T10:00:00+08:00"})
        hits = intercept_action(crud.store, "eo:task/no-object")
        assert {h.kind for h in hits} <= {"pose"}, f"不应有物理维度拦截：{hits}"

    def test_intercept_report_rewrites(self, crud):
        report = intercept_report(crud.store, "eo:task/push-box")
        assert not report.allowed
        assert len(report.rewrites) == len(report.interceptions) == 3


class TestDispatchConstraint:
    def test_dispatch_intercepted_status(self, crud):
        """下发超限任务 → 动作返回成功但任务置 intercepted（不是 executing）。"""
        reg = build_registry(crud)
        result = reg.execute("task.dispatch", actor="test", task_id="eo:task/push-box")
        assert result.ok
        assert crud.get("eo:task/push-box")["status"] == "intercepted"

    def test_dispatch_faulted_infeasible(self, crud):
        """故障注入后下发依赖该部件的任务 → failed + verdict=infeasible。"""
        crud.set_property("eo:part/ti5/six-axis-force", "health", "fault")
        reg = build_registry(crud)
        result = reg.execute("task.dispatch", actor="test", task_id="eo:task/grasp-egg")
        assert result.ok
        task = crud.get("eo:task/grasp-egg")
        assert task["status"] == "failed"
        assert task["verdict"] == "infeasible"

    def test_dispatch_feasible_passes(self, crud):
        """正常任务下发 → executing + verdict=feasible。"""
        reg = build_registry(crud)
        result = reg.execute("task.dispatch", actor="test", task_id="eo:task/carry-cup")
        assert result.ok
        task = crud.get("eo:task/carry-cup")
        assert task["status"] == "executing"
        assert task["verdict"] == "feasible"
