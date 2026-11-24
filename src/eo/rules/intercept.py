# -*- coding: utf-8 -*-
"""动作拦截（L2 规则层）：执行前检查，数据全部来自约束库（ADR-5）。

检查维度与数据来源：
  torque  Constraint(type=torque)：力矩 = 重量 × 力臂 vs threshold
  load    Constraint(type=load) ：物体重量 vs threshold
  pose    Constraint(type=pose) ：约束对象提供的 × 任务所需能力是否有交集
  surface 物体属性规则（归纳写回的参数改写）：slippery ⇒ 抓握力 ×1.5

改写建议优先取 Constraint.suggested_rewrite（数据驱动），
缺省时用容器感知启发式（容器可「先倒水」减负）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from ..graph.base import GraphStore
from .domain import ARM_LENGTH_M


@dataclass
class Interception:
    kind: str          # torque / load / pose / surface
    reason: str        # 拦截原因（人类可读）
    rewrite: str       # 改写建议


def intercept_action(store: GraphStore, task_id: str) -> List[Interception]:
    out: List[Interception] = []
    task = store.get_node(task_id)
    if task is None:
        return out

    objs = store.out_neighbors(task_id, "involves_object")
    obj = objs[0] if objs else None
    required = {c.id for c in store.out_neighbors(task_id, "requires_capability")}

    for c in [n for n in store.nodes() if n.type == "Constraint"]:
        kind = c.get("constraint_type")
        targets = store.out_neighbors(c.id, "constrains")
        if not targets:
            continue
        tgt = targets[0]
        threshold = c.get("threshold")

        if kind == "torque" and obj is not None and obj.get("weight_kg") is not None \
                and threshold is not None:
            torque = round(float(obj.get("weight_kg")) * ARM_LENGTH_M, 3)
            if torque > threshold:
                if c.get("suggested_rewrite"):
                    rewrite = c.get("suggested_rewrite")
                elif obj.get("is_container"):
                    rewrite = "溯因改写：先执行「倒水」减轻负载，再拿取"
                else:
                    rewrite = "参数改写：换肘部姿态缩短力臂，或改双手协作"
                out.append(Interception(
                    kind="torque",
                    reason=f"力矩 {torque} N·m > {threshold} N·m（约束 {c.id}：{c.get('expression')}）",
                    rewrite=rewrite,
                ))

        elif kind == "load" and obj is not None and obj.get("weight_kg") is not None \
                and threshold is not None:
            if obj.get("weight_kg") > threshold:
                rewrite = c.get("suggested_rewrite") or \
                    "改写计划：改用底盘推行，或分解为多次搬运"
                out.append(Interception(
                    kind="load",
                    reason=f"负载 {obj.get('weight_kg')} kg > {threshold} kg（约束 {c.id}：{c.get('expression')}）",
                    rewrite=rewrite,
                ))

        elif kind == "pose":
            caps_of_tgt = {n.id for n in store.out_neighbors(tgt.id, "provides_capability")}
            hit = sorted(caps_of_tgt & required)
            if hit:
                rewrite = c.get("suggested_rewrite") or "改写任务意义，或改派具备位形的机器人"
                out.append(Interception(
                    kind="pose",
                    reason=f"位形约束「{c.get('label')}」：{c.get('expression')}；"
                           f"{tgt.id} 提供的 {hit} 不可用",
                    rewrite=rewrite,
                ))

    # surface：归纳写回驱动的参数改写（L2 规则，不在约束库内）
    if obj is not None and obj.get("surface") == "slippery":
        out.append(Interception(
            kind="surface",
            reason=f"物体 {obj.id} 表面湿滑（slippery）",
            rewrite="参数改写：目标抓握力 ×1.5（写回规则：slippery⇒grip×1.5）",
        ))

    return out
