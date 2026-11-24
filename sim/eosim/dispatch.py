# -*- coding: utf-8 -*-
"""任务调度器：下发（Gate B 可达性+拦截）→ 执行推进 → 终态，全部经 ActionLog 审计。"""
from __future__ import annotations

from typing import Dict, Optional

from .clock import iso


class TaskDispatcher:
    def __init__(self, engine) -> None:
        self.engine = engine
        self._started: Dict[str, int] = {}

    # ---------------------------------------------------------------- 下发
    def dispatch(self, task_id: str, t: int) -> Optional[dict]:
        """Gate B：可达性判定（写回 verdict）+ 动作拦截 → 状态推进。"""
        env = self.engine
        task = env.store.get_node(task_id)
        if task is None:
            env.timeline.event(t, "dispatch", f"✗ 任务 {task_id} 不存在")
            return None

        r = env.reachability(task_id)
        env.log_action(t, "task.reachability_check", task_id, r.verdict,
                       detail="；".join(r.problems))

        if r.verdict == "infeasible":
            env.write([self._task_patch(task_id, t, "failed", verdict="infeasible")], t)
            env.timeline.event(t, "dispatch",
                               f"✗ {task_id}（{task.get('label')}）不可达：{r.problems}")
            return {"verdict": "infeasible", "problems": r.problems}

        hits = env.intercept(task_id)
        if hits:
            env.log_action(t, "task.intercept", task_id, "rewritten",
                           detail="；".join(f"[{h.kind}] {h.rewrite}" for h in hits))
            env.write([self._task_patch(task_id, t, "intercepted")], t)
            env.timeline.event(t, "dispatch", f"⛔ {task_id}（{task.get('label')}）触发 {len(hits)} 项拦截：")
            for h in hits:
                env.timeline.event(t, "intercept", f"    [{h.kind}] {h.reason} → {h.rewrite}")
            return {"verdict": "intercepted", "hits": hits}

        env.write([self._task_patch(task_id, t, "executing", verdict="feasible")], t)
        self._started[task_id] = t
        env.timeline.event(t, "dispatch", f"✓ {task_id}（{task.get('label')}）放行 → executing")
        return {"verdict": "feasible"}

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
    def reassign(self, task_id: str, robot_id: str, t: int) -> None:
        env = self.engine
        env.log_action(t, "task.reassign", task_id, "ok", detail=robot_id)
        env.write([self._task_patch(task_id, t, "pending", robot_id=robot_id)], t)
        env.timeline.event(t, "dispatch", f"→ {task_id} 改派至 {robot_id}")

    # ---------------------------------------------------------------- 辅助
    def _task_patch(self, task_id: str, t: int, status: str,
                    robot_id: Optional[str] = None,
                    verdict: Optional[str] = None) -> dict:
        """任务状态补丁（write() 按 id 浅合并，未提及的槽保留现值）。"""
        patch: dict = {"id": task_id, "type": "Task", "status": status,
                       "updated_at": iso(t)}
        if robot_id:
            patch["assigned_to"] = robot_id
        if verdict:
            patch["verdict"] = verdict
        return patch
