# -*- coding: utf-8 -*-
"""图推理接口（图推理 = 遍历 + 规则，调研 §2.6 的统一入口）。

- dependency_closure：任务的依赖闭包（能力/部件/约束/机器人）
- fault_impact：正向影响面（部件或故障事件 → 失效能力 → 受影响任务）
- trace_root_cause：反向根因溯源（症状 → 因果链 → 根因实体，结构化 + 证据）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .graph.base import GraphStore
from .rules.faults import propagate_fault, propagate_fault_event


@dataclass
class DependencyClosure:
    task_id: str
    capabilities: List[str] = field(default_factory=list)   # 所需能力
    parts: List[str] = field(default_factory=list)          # 提供部件
    constraints: List[str] = field(default_factory=list)    # 适用约束
    robot: Optional[str] = None                             # 指派机器人


@dataclass
class RootCause:
    entity: str             # 根因实体 id
    entity_type: str        # BodyPart / FaultEvent
    evidence: List[str] = field(default_factory=list)  # 因果链（每条一段）

    def __repr__(self) -> str:
        return f"RootCause({self.entity_type} {self.entity}, {' → '.join(self.evidence)})"


@dataclass
class RootCauseReport:
    symptom: str
    causes: List[RootCause] = field(default_factory=list)

    def __str__(self) -> str:
        if not self.causes:
            return f"症状 {self.symptom} 未定位到根因"
        lines = [f"症状 {self.symptom} 的根因："]
        for c in self.causes:
            lines.append(f"  {c.entity_type} {c.entity}")
            for ev in c.evidence:
                lines.append(f"      └─ {ev}")
        return "\n".join(lines)


# ---------------------------------------------------------------- 依赖闭包
def dependency_closure(store: GraphStore, task_id: str) -> DependencyClosure:
    """任务 → 能力 → 部件 → 约束 的依赖闭包。"""
    d = DependencyClosure(task_id=task_id)

    cap_ids = [c.id for c in store.out_neighbors(task_id, "requires_capability")]
    d.capabilities = cap_ids

    part_ids = set()
    for cap_id in cap_ids:
        for p in store.in_neighbors(cap_id, "provides_capability"):
            part_ids.add(p.id)
    d.parts = sorted(part_ids)

    for con in store.nodes():
        if con.type != "Constraint":
            continue
        if any(t.id in part_ids for t in store.out_neighbors(con.id, "constrains")):
            d.constraints.append(con.id)
    d.constraints = sorted(d.constraints)

    assigned = store.out_neighbors(task_id, "assigned_to")
    d.robot = assigned[0].id if assigned else None
    return d


# ---------------------------------------------------------------- 正向影响面
def fault_impact(store: GraphStore, source_id: str):
    """正向影响面：source 为故障部件（BodyPart）或故障事件（FaultEvent）。"""
    node = store.get_node(source_id)
    if node is None:
        from .rules.faults import FaultImpact
        return FaultImpact()
    if node.type == "FaultEvent":
        return propagate_fault_event(store, source_id)
    if node.type == "BodyPart":
        return propagate_fault(store, source_id)
    raise ValueError(f"不支持的故障源类型 {node.type}（应为 BodyPart 或 FaultEvent）")


# ---------------------------------------------------------------- 反向根因
def trace_root_cause(store: GraphStore, symptom_id: str) -> RootCauseReport:
    """反向根因溯源：症状（任务或能力）→ 依赖链 → 根因实体。

    根因两类：
      ① 提供部件 health ∈ {fault, degraded}
      ② 提供部件被活跃故障事件影响（事件 → 模式）
    """
    node = store.get_node(symptom_id)
    if node is None:
        return RootCauseReport(symptom_id)

    if node.type == "Task":
        caps = store.out_neighbors(symptom_id, "requires_capability")
        symptom_desc = f"任务 {node.get('label', symptom_id)}（{symptom_id}）"
    elif node.type == "Capability":
        caps = [node]
        symptom_desc = f"能力 {node.get('code', symptom_id)}（{symptom_id}）"
    else:
        return RootCauseReport(symptom_id)

    report = RootCauseReport(symptom_id)
    for cap in caps:
        for part in store.in_neighbors(cap.id, "provides_capability"):
            health = part.get("health", "ok")
            if health in ("fault", "degraded"):
                report.causes.append(RootCause(
                    entity=part.id, entity_type="BodyPart",
                    evidence=[f"{symptom_desc} ← 依赖能力 {cap.id} "
                              f"← 提供者 {part.id} 健康={health}"]))
            for ev in store.in_neighbors(part.id, "affects_bodypart"):
                if ev.get("status") != "active":
                    continue
                modes = store.out_neighbors(ev.id, "of_mode")
                mode_txt = f"（模式 {modes[0].id}）" if modes else ""
                report.causes.append(RootCause(
                    entity=ev.id, entity_type="FaultEvent",
                    evidence=[f"{symptom_desc} ← 依赖能力 {cap.id} "
                              f"← 提供者 {part.id} ← 活跃事件 {ev.id}{mode_txt}"]))
    return report
