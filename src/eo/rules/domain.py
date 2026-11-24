# -*- coding: utf-8 -*-
"""领域规则（L2 规则层，作为数据定义可热增改）。

对应三种推理：
  ① 演绎：属性 → 能力/结论（有把手⇒可抓取 / 易碎⇒需力控 / 有螺纹⇒需旋拧）
  ② 约束：数值（读约束库 Constraint：力矩/负载，超阈值⇒受约束）
  ③ 规则/归纳：表面湿滑 ⇒ 抓握力度 ×1.5

注意：② 的阈值一律读 Constraint 库（docs/01 ADR：拦截判定以约束库为准），
不在规则代码里写死数值。
"""
from __future__ import annotations

from typing import Any, Set

from ..graph.base import GraphStore
from .engine import Fact, Rule, nodes_of_type

# 力矩力臂（米）：来自约束库 expression 的物理参数占位，真实值从 URDF/标定取
ARM_LENGTH_M = 0.3


def _deduce_handle(store: GraphStore, facts: Set[Fact]) -> Set[Fact]:
    """① 演绎：有把手 ⇒ 可抓取"""
    out: Set[Fact] = set()
    for n in nodes_of_type(store, "Object"):
        if n.get("has_handle") is True:
            out.add((n.id, "graspable", True))
    return out


def _deduce_fragile(store: GraphStore, facts: Set[Fact]) -> Set[Fact]:
    """① 演绎：易碎 ⇒ 需力控"""
    out: Set[Fact] = set()
    for n in nodes_of_type(store, "Object"):
        if n.get("is_fragile") is True:
            out.add((n.id, "needs_force_control", True))
    return out


def _deduce_thread(store: GraphStore, facts: Set[Fact]) -> Set[Fact]:
    """① 演绎：有螺纹 ⇒ 需旋拧"""
    out: Set[Fact] = set()
    for n in nodes_of_type(store, "Object"):
        if n.get("has_thread") is True:
            out.add((n.id, "needs_screw", True))
    return out


def _surface_grip_factor(store: GraphStore, facts: Set[Fact]) -> Set[Fact]:
    """③ 规则/归纳：表面湿滑 ⇒ 抓握力度 ×1.5，干燥 ⇒ ×1.0"""
    out: Set[Fact] = set()
    for n in nodes_of_type(store, "Object"):
        surface = n.get("surface")
        if surface == "slippery":
            out.add((n.id, "grip_factor", 1.5))
        elif surface == "dry":
            out.add((n.id, "grip_factor", 1.0))
    return out


def _task_objects(store: GraphStore, task_id: str):
    objs = store.out_neighbors(task_id, "involves_object")
    return objs[0] if objs else None


def _torque_constraint(store: GraphStore, facts: Set[Fact]) -> Set[Fact]:
    """② 约束：力矩 = 重量 × 力臂，超约束库 torque 阈值 ⇒ 受约束（over_torque）"""
    out: Set[Fact] = set()
    for c in nodes_of_type(store, "Constraint"):
        if c.get("constraint_type") != "torque":
            continue
        limit: Any = c.get("threshold")
        if limit is None:
            continue
        for t in nodes_of_type(store, "Task"):
            obj = _task_objects(store, t.id)
            if obj is None or obj.get("weight_kg") is None:
                continue
            torque = round(float(obj.get("weight_kg")) * ARM_LENGTH_M, 3)
            if torque > limit:
                out.add((t.id, "over_torque", torque))
            else:
                out.add((t.id, "torque_ok", torque))
    return out


def _load_constraint(store: GraphStore, facts: Set[Fact]) -> Set[Fact]:
    """② 约束：负载超约束库 load 阈值 ⇒ 受约束（over_load）"""
    out: Set[Fact] = set()
    for c in nodes_of_type(store, "Constraint"):
        if c.get("constraint_type") != "load":
            continue
        limit: Any = c.get("threshold")
        if limit is None:
            continue
        for t in nodes_of_type(store, "Task"):
            obj = _task_objects(store, t.id)
            if obj is None or obj.get("weight_kg") is None:
                continue
            if obj.get("weight_kg") > limit:
                out.add((t.id, "over_load", float(obj.get("weight_kg"))))
    return out


DOMAIN_RULES: list[Rule] = [
    Rule("has_handle⇒graspable", "有把手 ⇒ 可抓取（演绎）", _deduce_handle),
    Rule("fragile⇒force_control", "易碎 ⇒ 需力控（演绎）", _deduce_fragile),
    Rule("thread⇒screw", "有螺纹 ⇒ 需旋拧（演绎）", _deduce_thread),
    Rule("surface⇒grip_factor", "表面状态 ⇒ 抓握力度系数（规则/归纳）", _surface_grip_factor),
    Rule("torque_constraint", "力矩=重量×力臂，超约束库 torque 阈值 ⇒ 受约束", _torque_constraint),
    Rule("load_constraint", "负载超约束库 load 阈值 ⇒ 受约束", _load_constraint),
]
