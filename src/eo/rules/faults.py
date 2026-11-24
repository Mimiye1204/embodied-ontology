# -*- coding: utf-8 -*-
"""故障传播推理（L2 规则层）。

传播依据 = FaultMode 故障模式库（ADR-1，数据驱动）：
  FaultEvent -of_mode→ FaultMode -affects_capability→ Capability ←-requires_capability- Task
  以及      FaultMode -affects_bodypart→ BodyPart

- 正向（影响面）：事件 → 模式 → 失效能力 → 受影响任务
- 反向（根因定位）：失败任务 → 依赖链回溯 → 可疑部件
- 兜底：事件无模式时按直接关联部件做结构化传播
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..graph.base import GraphStore


@dataclass
class FaultImpact:
    faulty_parts: List[str] = field(default_factory=list)
    lost_capabilities: List[str] = field(default_factory=list)
    affected_tasks: List[str] = field(default_factory=list)


def _tasks_of_capabilities(store: GraphStore, cap_ids: List[str]) -> List[str]:
    task_ids = set()
    for cap_id in cap_ids:
        for task in store.in_neighbors(cap_id, "requires_capability"):
            task_ids.add(task.id)
    return sorted(task_ids)


def propagate_fault_event(store: GraphStore, event_id: str) -> FaultImpact:
    """正向传播：故障事件（优先走模式库）→ 影响面。"""
    impact = FaultImpact()

    modes = store.out_neighbors(event_id, "of_mode")
    if modes:
        mode = modes[0]
        impact.faulty_parts = sorted(p.id for p in store.out_neighbors(mode.id, "affects_bodypart"))
        impact.lost_capabilities = sorted(
            c.id for c in store.out_neighbors(mode.id, "affects_capability"))
    else:
        # 兜底：无模式，按事件直接关联部件做结构化传播
        for part in store.out_neighbors(event_id, "affects_bodypart"):
            impact.faulty_parts.append(part.id)
            impact.lost_capabilities += sorted(
                c.id for c in store.out_neighbors(part.id, "provides_capability"))

    impact.affected_tasks = _tasks_of_capabilities(store, impact.lost_capabilities)
    return impact


def propagate_fault(store: GraphStore, bodypart_id: str) -> FaultImpact:
    """正向传播：直接给故障部件（不经过模式库）。"""
    impact = FaultImpact(faulty_parts=[bodypart_id])
    impact.lost_capabilities = sorted(
        c.id for c in store.out_neighbors(bodypart_id, "provides_capability"))
    impact.affected_tasks = _tasks_of_capabilities(store, impact.lost_capabilities)
    return impact


def root_cause(store: GraphStore, task_id: str) -> List[str]:
    """反向根因定位：失败任务依赖链上 health ∈ {fault, degraded} 的部件。"""
    suspects: List[str] = []
    for cap in store.out_neighbors(task_id, "requires_capability"):
        for part in store.in_neighbors(cap.id, "provides_capability"):
            if part.get("health", "ok") in ("fault", "degraded"):
                suspects.append(part.id)
    return sorted(set(suspects))
