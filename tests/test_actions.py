# -*- coding: utf-8 -*-
"""Action 绑定模型单元测试：受控动作的执行管线（参数/目标校验 + 审计）。"""
from __future__ import annotations

from eo.actions import build_registry


def _reg(crud):
    return build_registry(crud)


class TestDispatch:
    def test_feasible_dispatch(self, crud):
        result = _reg(crud).execute("task.dispatch", actor="test", task_id="eo:task/carry-cup")
        assert result.ok and result.audit_log_id
        task = crud.get("eo:task/carry-cup")
        assert task["status"] == "executing" and task["verdict"] == "feasible"
        assert crud.get(result.audit_log_id)["action_type"] == "task.dispatch"

    def test_infeasible_dispatch(self, crud):
        # 注入故障：六维力失效 → 抓鸡蛋依赖力控 → 不可达
        crud.set_property("eo:part/ti5/six-axis-force", "health", "fault")
        result = _reg(crud).execute("task.dispatch", actor="test", task_id="eo:task/grasp-egg")
        assert result.ok, "动作本身执行成功（业务结论是不可达）"
        assert crud.get("eo:task/grasp-egg")["status"] == "failed"
        assert any("不可达" in m for m in result.messages)


class TestValidation:
    def test_missing_target(self, crud):
        r = _reg(crud).execute("task.dispatch", actor="test", task_id="eo:task/ghost")
        assert not r.ok and "不存在" in r.messages[0]

    def test_wrong_target_type(self, crud):
        r = _reg(crud).execute("fault.report", actor="test", mode_id="eo:object/cup")
        assert not r.ok

    def test_reassign_non_robot(self, crud):
        r = _reg(crud).execute("task.reassign", actor="test", task_id="eo:task/carry-cup",
                               robot_id="eo:object/cup")
        assert not r.ok

    def test_writeback_gate_a_rejected(self, crud):
        r = _reg(crud).execute("knowledge.writeback", actor="test", entity_id="eo:object/cup",
                               patch={"surface": "wet"})
        assert not r.ok
        assert crud.get(r.audit_log_id)["result"] == "failed"

    def test_missing_params(self, crud):
        r = _reg(crud).execute("task.dispatch", actor="test")
        assert not r.ok and "缺少参数" in r.messages[0]


class TestAudit:
    def test_seq_no_collision(self, crud):
        r1 = _reg(crud).execute("task.dispatch", actor="a", task_id="eo:task/carry-cup")
        r2 = _reg(crud).execute("task.dispatch", actor="b", task_id="eo:task/carry-cup")
        assert r1.audit_log_id != r2.audit_log_id
        assert crud.get(r1.audit_log_id) and crud.get(r2.audit_log_id)

    def test_fault_report(self, crud):
        r = _reg(crud).execute("fault.report", actor="test", mode_id="eo:faultmode/force-sensor-failure")
        assert r.ok
        assert crud.get("eo:part/ti5/six-axis-force")["health"] == "fault"
        assert any("受影响任务" in m for m in r.messages)
