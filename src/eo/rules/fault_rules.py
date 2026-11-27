# -*- coding: utf-8 -*-
"""故障传播规则（声明式，冗余感知）。

核心语义：能力「失效」（lost）当且仅当其**所有提供部件都故障**（无健康提供者）。
这与可达性判定（check_reachability）的冗余逻辑一致——冗余部件仍可用，能力不失效。

故障模式库（FaultMode.affects_capability）用于 fault.report 动作与根因溯源
（trace_root_cause：事件 → 模式），前向传播由部件健康状态驱动。
"""
from __future__ import annotations

from .framework import RuleContext, RuleSpec


def _capability_lost(ctx: RuleContext) -> None:
    """能力失效：所有提供部件均故障（冗余感知）。"""
    for cap in ctx.nodes("Capability"):
        providers = ctx.in_links(cap.id, "provides_capability")
        if not providers:
            continue
        healths = [p.get("health", "ok") for p in providers]
        if all(h == "fault" for h in healths):
            faulted = sorted(p.id for p in providers if p.get("health") == "fault")
            ctx.assert_(cap.id, "lost", True,
                        evidence=[f"提供者全部故障：{faulted}"])


def _cap_lost_affects_tasks(ctx: RuleContext) -> None:
    """失效能力 → 依赖它的任务受影响。"""
    for cap in ctx.nodes("Capability"):
        if ctx.known(cap.id, "lost") is None:
            continue
        for task in ctx.in_links(cap.id, "requires_capability"):
            ctx.assert_(task.id, "affected_by_fault", True,
                        evidence=[f"依赖失效能力 {cap.id}"])


FAULT_RULES = [
    RuleSpec("capability_lost", "能力提供者全部故障 → 失效（冗余感知）",
             category="fault", priority=500, fire=_capability_lost),
    RuleSpec("capability_lost→task_affected", "失效能力 → 依赖任务受影响",
             category="fault", priority=400, fire=_cap_lost_affects_tasks),
]
