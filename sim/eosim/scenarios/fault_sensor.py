# -*- coding: utf-8 -*-
"""场景 1 · fault_sensor：模式库故障注入 → 传播 → 任务失败 → 根因回溯。"""
from __future__ import annotations

from .base import Scenario


class FaultSensorScenario(Scenario):
    name = "fault_sensor"
    description = "注入六维力失效模式 → 传播 → 抓鸡蛋不可达、端杯子不受影响 → 根因回溯"
    duration = 14

    def tick(self, env, t: int) -> None:
        if t == 2:
            env.inject_fault("eo:faultmode/force-sensor-failure", t)

        if t == 5:
            env.timeline.event(t, "dispatch", "── 下发「抓鸡蛋」（依赖力控）──")
            env.dispatcher.dispatch("eo:task/grasp-egg", t)

        if t == 7:
            env.timeline.event(t, "dispatch", "── 下发「端杯子」（只依赖包握）──")
            env.dispatcher.dispatch("eo:task/carry-cup", t)

        if t == 9:
            suspects = env.root_cause("eo:task/grasp-egg")
            env.timeline.event(t, "diagnose",
                               f"反向根因：抓鸡蛋失败 → 依赖链回溯 → 可疑部件 {suspects}")
