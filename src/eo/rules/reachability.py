# -*- coding: utf-8 -*-
"""任务可达性判断（L2 规则层）：任务 → 能力 → 部件覆盖检查，含指派机器人范围。

范围规则（docs/02 §7）：
  - 已指派：提供能力的部件必须属于指派机器人的部件树（has_part 根 + part_of 链）
  - 未指派：按全队能力评估，proof 中注明

verdict 与枚举 VerdictType 一致：feasible / constrained / infeasible
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..graph.base import GraphStore
from ..graph.traversal import neighbors, traverse


@dataclass
class ReachabilityResult:
    task_id: str
    verdict: str                      # feasible / constrained / infeasible
    proof: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)


def part_of_robot(store: GraphStore, part_id: str, robot_id: str) -> bool:
    """判断部件是否属于机器人。

    part_of 边方向为「子 → 父」：沿 part_of 出边上溯到树根，看根是否挂在机器人 has_part 下。
    """
    roots = set(neighbors(store, robot_id, {"has_part"}, "out"))
    # 部件即根，或其 part_of 出边闭包命中根，都属于该机器人
    return part_id in roots or bool(traverse(store, part_id, {"part_of"}, "out") & roots)


def robot_of_part(store: GraphStore, part_id: str) -> Optional[str]:
    """反向：部件 → 所属机器人 id（无归属 → None）。"""
    for robot in store.nodes():
        if robot.type == "Robot" and part_of_robot(store, part_id, robot.id):
            return robot.id
    return None


def check_reachability(store: GraphStore, task_id: str) -> ReachabilityResult:
    task = store.get_node(task_id)
    if task is None:
        return ReachabilityResult(task_id, "infeasible", [], [f"任务 {task_id} 不存在"])

    result = ReachabilityResult(task_id, "feasible")

    assigned = store.out_neighbors(task_id, "assigned_to")
    robot = assigned[0] if assigned else None
    if robot:
        result.proof.append(f"指派机器人：{robot.id}（{robot.get('label') or ''}）")
    else:
        result.proof.append("未指派机器人：按全队能力评估")

    required_caps = store.out_neighbors(task_id, "requires_capability")
    result.proof.append(f"需要 {len(required_caps)} 项能力：{[c.id for c in required_caps]}")

    for cap in required_caps:
        providers = store.in_neighbors(cap.id, "provides_capability")
        if not providers:
            result.problems.append(f"能力 {cap.id} 没有任何部件提供")
            result.proof.append(f"  ✗ {cap.id}：无提供者 → 不可达")
            result.verdict = "infeasible"
            continue

        if robot:
            in_scope = [p for p in providers if part_of_robot(store, p.id, robot.id)]
            if not in_scope:
                result.problems.append(
                    f"能力 {cap.id} 的提供部件 {[p.id for p in providers]} 不属于指派机器人 {robot.id}")
                result.proof.append(
                    f"  ✗ {cap.id}：提供者 {[p.id for p in providers]} 不在 {robot.id} 部件树内")
                result.verdict = "infeasible"
                continue
            providers = in_scope

        healthy = [p for p in providers if p.get("health", "ok") == "ok"]
        degraded = [p for p in providers if p.get("health") == "degraded"]
        faulty = [p for p in providers if p.get("health") == "fault"]

        if healthy:
            result.proof.append(f"  ✓ {cap.id}：由 {[p.id for p in healthy]} 正常提供")
            if degraded:
                result.proof.append(f"    （另有降级部件 {[p.id for p in degraded]}，冗余可用）")
        elif degraded and not faulty:
            result.proof.append(f"  ⚠ {cap.id}：提供部件 {[p.id for p in degraded]} 均降级")
            result.problems.append(f"能力 {cap.id} 仅由降级部件提供")
            if result.verdict != "infeasible":
                result.verdict = "constrained"
        else:
            result.proof.append(f"  ✗ {cap.id}：提供部件 {[p.id for p in providers]} 均故障")
            result.problems.append(f"能力 {cap.id} 的提供部件故障")
            result.verdict = "infeasible"

    return result
