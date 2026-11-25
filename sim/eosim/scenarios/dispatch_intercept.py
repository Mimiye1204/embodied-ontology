# -*- coding: utf-8 -*-
"""场景 2 · dispatch_intercept：下发超限任务 → 约束库拦截 → 改写建议。"""
from __future__ import annotations

from .base import Scenario


class DispatchInterceptScenario(Scenario):
    name = "dispatch_intercept"
    description = "下发「推箱子」→ 三维拦截（力矩/负载/抓握力）→ 改写建议"
    duration = 10

    def tick(self, env, t: int) -> None:
        if t == 2:
            env.timeline.event(t, "dispatch", "── 下发「推箱子」（30kg 超限）──")
            env.dispatcher.dispatch("eo:task/push-box", t)

        if t == 6:
            env.timeline.event(t, "dispatch", "── 下发「端杯子」（正常，放行）──")
            env.dispatcher.dispatch("eo:task/carry-cup", t)
