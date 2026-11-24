# -*- coding: utf-8 -*-
"""场景 3 · slip_loop：湿滑闭环 —— 力读数骤降 → 检测 → 写回本体 → 规则重跑 → 拦截改写。"""
from __future__ import annotations

from .base import Scenario


class SlipLoopScenario(Scenario):
    name = "slip_loop"
    description = "力读数异常剖面（12N→4N）→ 滑移检测 → 写回 surface=slippery → 力度×1.5 拦截"
    duration = 16

    def setup(self, env) -> None:
        env.runtime.set_anomaly("force_reading", {
            "type": "decay", "from": 3, "to": 7, "start": 12.0, "end": 4.0,
            "hold": True,
        })

    def tick(self, env, t: int) -> None:
        if t == 2:
            env.timeline.event(t, "dispatch", "── 下发「端杯子」（此时杯面 dry，放行）──")
            env.dispatcher.dispatch("eo:task/carry-cup", t)

        if t == 8:
            env.timeline.event(t, "telemetry", "── 时序库滑移检测（读 force_reading 序列）──")
            alarm = env.runtime.detect_drop("eo:part/ti5/six-axis-force", "force_reading")
            if alarm:
                env.timeline.event(t, "telemetry",
                                   f"⚠ 力读数 {alarm['first']} N → {alarm['last']} N "
                                   f"（骤降 {alarm['drop_pct']}%）")
                env.timeline.event(t, "writeback", "归纳写回：eo:object/cup.surface = slippery")
                env.log_action(t, "knowledge.writeback", "eo:object/cup", "ok",
                               detail="surface=slippery（滑移检测归纳）")
                if env.write([{"id": "eo:object/cup", "type": "Object",
                               "surface": "slippery"}], t):
                    grip = next((v for s, p, v in env.facts
                                 if s == "eo:object/cup" and p == "grip_factor"), None)
                    env.timeline.event(t, "rules",
                                       f"规则重跑：eo:object/cup grip_factor = {grip}")
                else:
                    env.timeline.event(t, "writeback", "✗ 写回被 Gate A 拒绝")

        if t == 11:
            env.timeline.event(t, "dispatch", "── 再次下发「端杯子」（湿滑 → 拦截）──")
            env.dispatcher.dispatch("eo:task/carry-cup", t)
