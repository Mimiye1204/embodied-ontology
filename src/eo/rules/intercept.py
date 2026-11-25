# -*- coding: utf-8 -*-
"""动作拦截（L2 规则层，docs/04 §2.7 插件化落地）。

拦截器注册表：每个拦截器检查一个维度（torque/load/gripper/pose/surface），
数据全部来自约束库（ADR-5）与物体属性，不写死在代码里：

  torque   Constraint(type=torque)  ：力矩 = 重量 × 力臂 vs threshold
  load     Constraint(type=load)    ：物体重量 vs threshold
  gripper  Constraint(type=gripper) ：所需抓握力 = m·g·k_surface vs threshold
  pose     Constraint(type=pose)    ：约束对象提供的 × 任务所需能力 有交集
  surface  物体属性（归纳写回参数改写）：slippery ⇒ 抓握力 ×1.5

改写建议优先取 Constraint.suggested_rewrite（数据驱动）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ..graph.base import GraphStore
from .domain import ARM_LENGTH_M

GRAVITY = 9.8          # 抓握力估算重力系数
SURFACE_GRIP = {"slippery": 1.5, "dry": 1.0}


@dataclass
class Interception:
    kind: str          # torque / load / gripper / pose / surface
    reason: str        # 拦截原因（人类可读）
    rewrite: str       # 改写建议


@dataclass
class InterceptionReport:
    task_id: str
    allowed: bool
    interceptions: List[Interception] = field(default_factory=list)

    @property
    def rewrites(self) -> List[str]:
        return [i.rewrite for i in self.interceptions]


Interceptor = Callable[[GraphStore, str], Optional[Interception]]


# ================================================================ 辅助
def _task(store: GraphStore, task_id: str):
    return store.get_node(task_id)


def _object_of(store: GraphStore, task_id: str):
    objs = store.out_neighbors(task_id, "involves_object")
    return objs[0] if objs else None


def _constraints(store: GraphStore, kind: str):
    for c in store.nodes():
        if c.type == "Constraint" and c.get("constraint_type") == kind:
            yield c


def _rewrite_or(c, fallback: str) -> str:
    return c.get("suggested_rewrite") or fallback


# ================================================================ 拦截器
def _torque_interceptor(store: GraphStore, task_id: str) -> Optional[Interception]:
    obj = _object_of(store, task_id)
    if obj is None or obj.get("weight_kg") is None:
        return None
    for c in _constraints(store, "torque"):
        if c.get("threshold") is None:
            continue
        torque = round(float(obj.get("weight_kg")) * ARM_LENGTH_M, 3)
        if torque > c.get("threshold"):
            if obj.get("is_container"):
                fallback = "溯因改写：先执行「倒水」减轻负载，再拿取"
            else:
                fallback = "参数改写：换肘部姿态缩短力臂，或改双手协作"
            return Interception(
                kind="torque",
                reason=f"力矩 {torque} N·m > {c.get('threshold')} N·m"
                       f"（约束 {c.id}：{c.get('expression')}）",
                rewrite=_rewrite_or(c, fallback),
            )
    return None


def _load_interceptor(store: GraphStore, task_id: str) -> Optional[Interception]:
    obj = _object_of(store, task_id)
    if obj is None or obj.get("weight_kg") is None:
        return None
    for c in _constraints(store, "load"):
        if c.get("threshold") is None:
            continue
        if obj.get("weight_kg") > c.get("threshold"):
            return Interception(
                kind="load",
                reason=f"负载 {obj.get('weight_kg')} kg > {c.get('threshold')} kg"
                       f"（约束 {c.id}：{c.get('expression')}）",
                rewrite=_rewrite_or(c, "改写计划：改用底盘推行，或分解为多次搬运"),
            )
    return None


def _gripper_interceptor(store: GraphStore, task_id: str) -> Optional[Interception]:
    obj = _object_of(store, task_id)
    if obj is None or obj.get("weight_kg") is None:
        return None
    k = SURFACE_GRIP.get(obj.get("surface"), 1.0)
    required = round(float(obj.get("weight_kg")) * GRAVITY * k, 2)
    for c in _constraints(store, "gripper"):
        if c.get("threshold") is None:
            continue
        if required > c.get("threshold"):
            return Interception(
                kind="gripper",
                reason=f"所需抓握力 {required} N（{obj.id} 重 {obj.get('weight_kg')} kg"
                       f" × 表面系数 ×{k}）> {c.get('threshold')} N（约束 {c.id}）",
                rewrite=_rewrite_or(c, "改用双手协同或增大夹持接触面积"),
            )
    return None


def _pose_interceptor(store: GraphStore, task_id: str) -> Optional[Interception]:
    required = {n.id for n in store.out_neighbors(task_id, "requires_capability")}
    for c in _constraints(store, "pose"):
        for tgt in store.out_neighbors(c.id, "constrains"):
            caps = {n.id for n in store.out_neighbors(tgt.id, "provides_capability")}
            hit = sorted(caps & required)
            if hit:
                return Interception(
                    kind="pose",
                    reason=f"位形约束「{c.get('label')}」：{c.get('expression')}；"
                           f"{tgt.id} 提供的 {hit} 不可用",
                    rewrite=_rewrite_or(c, "改写任务意义，或改派具备位形的机器人"),
                )
    return None


def _surface_interceptor(store: GraphStore, task_id: str) -> Optional[Interception]:
    obj = _object_of(store, task_id)
    if obj is not None and obj.get("surface") == "slippery":
        return Interception(
            kind="surface",
            reason=f"物体 {obj.id} 表面湿滑（slippery）",
            rewrite="参数改写：目标抓握力 ×1.5（写回规则：slippery⇒grip×1.5）",
        )
    return None


INTERCEPTORS: List[Interceptor] = [
    _torque_interceptor,
    _load_interceptor,
    _gripper_interceptor,
    _pose_interceptor,
    _surface_interceptor,
]


# ================================================================ 入口
def intercept_action(store: GraphStore, task_id: str) -> List[Interception]:
    """执行前检查，返回所有命中拦截项（空列表 = 放行）。"""
    out: List[Interception] = []
    for inter in INTERCEPTORS:
        hit = inter(store, task_id)
        if hit is not None:
            out.append(hit)
    return out


def intercept_report(store: GraphStore, task_id: str) -> InterceptionReport:
    """结构化拦截报告（allowed + 拦截项 + 改写建议）。"""
    hits = intercept_action(store, task_id)
    return InterceptionReport(task_id=task_id, allowed=not hits, interceptions=hits)
