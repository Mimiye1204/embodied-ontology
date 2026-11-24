# -*- coding: utf-8 -*-
"""任务调度器：经 Action 注册表执行受控动作（task.dispatch / task.reassign），
动作内部完成 Gate B 检查与自动审计；本模块只做执行推进与时间线输出。"""
from __future__ import annotations

from typing import Dict, Optional

from .clock import iso


class TaskDispatcher:
    def __init__(self, engine) -> None:
        self.engine = engine
        self._started: Dict[str, int] = {}

    # ---------------------------------------------------------------- 下发
    def dispatch(self, task_id: str, t: int) -> Optional[dict]:
        """task.dispatch 动作：可达性 + 拦截 → 状态迁移（结果含消息与审计 id）。"""
        env = self.engine
        result = env.actions.execute("task.dispatch", actor="simulation", task_id=task_id)
        if result is None:
            env.timeline.event(t, "dispatch", "✗ 未知动作 task.dispatch")
            return None
        for m in result.messages:
            env.timeline.event(t, "dispatch", m)
        task = env.crud.get(task_id)
        if result.ok and task and task.get("status") == "executing":
            self._started[task_id] = t
        return {"ok": result.ok, "messages": result.messages,
                "audit": result.audit_log_id}

    # ---------------------------------------------------------------- 推进
    def advance(self, t: int) -> None:
        """执行中任务 3 步后成功；失败任务保持终态。"""
        env = self.engine
        for task_id, start in list(self._started.items()):
            if t - start < 3:
                continue
            env.write([self._task_patch(task_id, t, "succeeded")], t)
            env.log_action(t, "task.execute", task_id, "ok")
            env.timeline.event(t, "execute", f"✓ {task_id} 执行完成 → succeeded")
            del self._started[task_id]

    # ---------------------------------------------------------------- 改派
    def reassign(self, task_id: str, robot_id: str, t: int) -> Optional[dict]:
        env = self.engine
        result = env.actions.execute("task.reassign", actor="simulation",
                                     task_id=task_id, robot_id=robot_id)
        if result is None:
            env.timeline.event(t, "dispatch", "✗ 未知动作 task.reassign")
            return None
        for m in result.messages:
            env.timeline.event(t, "dispatch", m)
        return {"ok": result.ok}

    # ---------------------------------------------------------------- 辅助
    def _task_patch(self, task_id: str, t: int, status: str) -> dict:
        """任务状态补丁（CRUD.apply 按 id 浅合并，未提及的槽保留现值）。"""
        return {"id": task_id, "type": "Task", "status": status, "updated_at": iso(t)}
