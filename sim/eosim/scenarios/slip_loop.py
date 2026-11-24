# -*- coding: utf-8 -*-
"""场景 3 · slip_loop：湿滑闭环 —— 监测规则（读时序绑定动态属性）→ 归纳断言
→ 声明式动作绑定（knowledge.writeback）→ Gate A 写回 → 规则重推 → 拦截改写。

本场景是「时序绑定 + 规则框架 + Action 模型」三件套的集成演示。
"""
from __future__ import annotations

from eo.rules.framework import RuleContext, RuleSpec

from .base import Scenario

SLIP_FORCE_THRESHOLD = 5.0


def _slip_monitor(ctx: RuleContext) -> None:
    """监测规则：执行中任务涉及的物体，抓握力读数（动态属性）跌破阈值 ⇒ 滑移。"""
    for t in ctx.nodes("Task"):
        if t.get("status") != "executing":
            continue
        objs = ctx.out_links(t.id, "involves_object")
        obj = objs[0] if objs else None
        if obj is None or obj.get("surface") == "slippery":
            continue
        force = ctx.dynamic("eo:part/ti5/six-axis-force", "current_force")
        if force is not None and force < SLIP_FORCE_THRESHOLD:
            ctx.note(f"⚠ {t.id} 执行中，current_force = {force} N < {SLIP_FORCE_THRESHOLD} N → 滑移")
            ctx.assert_(obj.id, "slip", True, evidence=[
                f"时序: {t.id} 执行中，{obj.id} 被握，current_force = {force} N"])


# 规则即数据：断言新事实时按声明自动触发写回动作（entity_id 取断言主体 {s}）
SLIP_MONITOR_RULE = RuleSpec(
    name="slip_monitor",
    description="监测：抓握力跌破阈值 ⇒ 物体滑移（归纳）",
    category="monitoring",
    priority=50,
    fire=_slip_monitor,
    actions=[{
        "action": "knowledge.writeback",
        "params": {"entity_id": "{s}", "patch": {"surface": "slippery"}},
    }],
)


class SlipLoopScenario(Scenario):
    name = "slip_loop"
    description = "力读数异常剖面（12N→4N）→ 监测规则+动态属性 → 动作写回 slippery → 力度×1.5 拦截"
    duration = 16

    def setup(self, env) -> None:
        env.runtime.set_anomaly("force_reading", {
            "type": "decay", "from": 3, "to": 7, "start": 12.0, "end": 4.0,
            "hold": True,
        })
        env.rules.add_rule(SLIP_MONITOR_RULE)

    def tick(self, env, t: int) -> None:
        if t == 5:
            env.timeline.event(t, "dispatch", "── 下发「端杯子」（此时杯面 dry，放行）──")
            env.dispatcher.dispatch("eo:task/carry-cup", t)

        if t == 8:
            env.timeline.event(t, "telemetry", "── 规则引擎重跑（监测规则读时序绑定动态属性）──")
            env.rules.run()
            for note in env.rules.notes:
                env.timeline.event(t, "monitor", note)
            for res in env.rules.action_results:
                for m in res.messages:
                    env.timeline.event(t, "action", m)
                if res.audit_log_id:
                    env.timeline.event(t, "audit", f"审计落库 {res.audit_log_id}")
            grip = env.rules.facts.get(("eo:object/cup", "grip_factor"))
            if grip:
                env.timeline.event(t, "rules",
                                   f"规则重推：eo:object/cup grip_factor = {grip.v}")

        if t == 11:
            env.timeline.event(t, "dispatch", "── 再次下发「端杯子」（湿滑 → 拦截）──")
            env.dispatcher.dispatch("eo:task/carry-cup", t)
