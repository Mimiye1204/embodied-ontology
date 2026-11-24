# -*- coding: utf-8 -*-
"""故障注入器：经 fault.report 动作上报（建事件 + 部件置 fault + 模式库传播 + 审计）。"""
from __future__ import annotations

from typing import Optional


class FaultInjector:
    def __init__(self, engine) -> None:
        self.engine = engine

    def inject(self, mode_id: str, t: int) -> Optional[dict]:
        env = self.engine
        result = env.actions.execute("fault.report", actor="simulation", mode_id=mode_id)
        if result is None:
            env.timeline.event(t, "fault", "✗ 未知动作 fault.report")
            return None
        for m in result.messages:
            env.timeline.event(t, "fault", m)
        return {"ok": result.ok, "target": result.target, "audit": result.audit_log_id}
