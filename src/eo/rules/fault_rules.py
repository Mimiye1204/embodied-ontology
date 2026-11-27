# -*- coding: utf-8 -*-
"""故障传播规则（声明式，RuleSpec 融入规则引擎）。

把故障传播从「过程式遍历」升级为「规则推导」，推导出的结论是带证明链的事实：
  - (capability, "lost", True)          能力失效
  - (task, "affected_by_fault", True)   任务受故障影响

两条触发路径（互补）：
  ① 部件故障：BodyPart.health=fault ──provides_capability──> 能力失效
  ② 故障事件：活跃 FaultEvent ──of_mode──> FaultMode ──affects_capability──> 能力失效
  ③ 级联：失效能力 ──requires_capability(反向)──> 依赖任务受影响

优先级保证单轮内完成整条链（①/② 先于 ③）。explain() 可回溯「为什么这个任务受影响」。
"""
from __future__ import annotations

from .framework import RuleContext, RuleSpec


def _part_fault(ctx: RuleContext) -> None:
    """① 故障部件 → 提供的能力失效。"""
    for part in ctx.nodes("BodyPart"):
        if part.get("health") != "fault":
            continue
        for cap in ctx.out_links(part.id, "provides_capability"):
            ctx.assert_(cap.id, "lost", True,
                        evidence=[f"故障部件 {part.id} 无法提供该能力"])


def _event_fault(ctx: RuleContext) -> None:
    """② 活跃故障事件 → 模式 → 能力失效（模式库驱动）。"""
    for ev in ctx.nodes("FaultEvent"):
        if ev.get("status") != "active":
            continue
        for mode in ctx.out_links(ev.id, "of_mode"):
            for cap in ctx.out_links(mode.id, "affects_capability"):
                ctx.assert_(cap.id, "lost", True,
                            evidence=[f"活跃事件 {ev.id}（{ev.get('label', '')}）"
                                      f"关联模式 {mode.id}"])


def _cap_lost_affects_tasks(ctx: RuleContext) -> None:
    """③ 失效能力 → 依赖它的任务受影响。"""
    for cap in ctx.nodes("Capability"):
        if ctx.known(cap.id, "lost") is None:
            continue
        for task in ctx.in_links(cap.id, "requires_capability"):
            ctx.assert_(task.id, "affected_by_fault", True,
                        evidence=[f"依赖失效能力 {cap.id}"])


FAULT_RULES = [
    RuleSpec("part_fault→capability_lost", "故障部件 → 提供能力失效",
             category="fault", priority=500, fire=_part_fault),
    RuleSpec("event→mode→capability_lost", "活跃故障事件 → 模式 → 能力失效",
             category="fault", priority=500, fire=_event_fault),
    RuleSpec("capability_lost→task_affected", "失效能力 → 依赖任务受影响",
             category="fault", priority=400, fire=_cap_lost_affects_tasks),
]
