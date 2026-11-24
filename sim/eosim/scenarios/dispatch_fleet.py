# -*- coding: utf-8 -*-
"""场景 2 · dispatch_fleet：编队可达性 —— 派错机器人 → 不可达 → 改派 → 放行。"""
from __future__ import annotations

from .base import Scenario


class DispatchFleetScenario(Scenario):
    name = "dispatch_fleet"
    description = "端杯子派给豹小秘2 → 不可达（部件树范围）→ 改派 TI5 → 放行执行"
    duration = 14

    def tick(self, env, t: int) -> None:
        if t == 2:
            env.timeline.event(t, "dispatch", "── 下发「端杯子」→ 豹小秘2（无手臂）──")
            env.dispatcher.dispatch("eo:task/carry-cup-by-bx2", t)

        if t == 5:
            env.timeline.event(t, "dispatch", "── 改派 TI5 并重新下发 ──")
            env.dispatcher.reassign("eo:task/carry-cup-by-bx2", "eo:robot/ti5", t)

        if t == 6:
            env.dispatcher.dispatch("eo:task/carry-cup-by-bx2", t)
