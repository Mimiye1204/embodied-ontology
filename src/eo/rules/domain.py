# -*- coding: utf-8 -*-
"""领域规则（L2 规则层，规则即数据 —— RuleSpec 定义，可热增改）。

对应三种推理（每条断言带证据，可用 RuleEngine.explain 回溯证明链）：
  ① 演绎：属性 → 能力/结论（有把手⇒可抓取 / 易碎⇒需力控 / 有螺纹⇒需旋拧）
  ② 约束：数值（读约束库 Constraint：力矩/负载，超阈值⇒受约束）
  ③ 归纳：表面湿滑 ⇒ 抓握力度 ×1.5

注意：② 的阈值一律读 Constraint 库（docs/01 ADR：拦截判定以约束库为准），
不在规则代码里写死数值。
"""
from __future__ import annotations

from typing import Any, List

from .framework import RuleContext, RuleSpec

# 力矩力臂（米）：来自约束库 expression 的物理参数占位，真实值从 URDF/标定取
ARM_LENGTH_M = 0.3


def _deduce_handle(ctx: RuleContext) -> None:
    """① 演绎：有把手 ⇒ 可抓取"""
    for n in ctx.nodes("Object"):
        if n.get("has_handle") is True:
            ctx.assert_(n.id, "graspable", True,
                        evidence=[f"图: {n.id}.has_handle = true"])


def _deduce_fragile(ctx: RuleContext) -> None:
    """① 演绎：易碎 ⇒ 需力控"""
    for n in ctx.nodes("Object"):
        if n.get("is_fragile") is True:
            ctx.assert_(n.id, "needs_force_control", True,
                        evidence=[f"图: {n.id}.is_fragile = true"])


def _deduce_thread(ctx: RuleContext) -> None:
    """① 演绎：有螺纹 ⇒ 需旋拧"""
    for n in ctx.nodes("Object"):
        if n.get("has_thread") is True:
            ctx.assert_(n.id, "needs_screw", True,
                        evidence=[f"图: {n.id}.has_thread = true"])


def _surface_grip_factor(ctx: RuleContext) -> None:
    """③ 规则/归纳：表面湿滑 ⇒ 抓握力度 ×1.5，干燥 ⇒ ×1.0"""
    for n in ctx.nodes("Object"):
        surface = n.get("surface")
        if surface == "slippery":
            ctx.assert_(n.id, "grip_factor", 1.5,
                        evidence=[f"图: {n.id}.surface = slippery"])
        elif surface == "dry":
            ctx.assert_(n.id, "grip_factor", 1.0,
                        evidence=[f"图: {n.id}.surface = dry"])


def _task_objects(ctx: RuleContext, task_id: str):
    objs = ctx.out_links(task_id, "involves_object")
    return objs[0] if objs else None


def _torque_constraint(ctx: RuleContext) -> None:
    """② 约束：力矩 = 重量 × 力臂，超约束库 torque 阈值 ⇒ 受约束（over_torque）"""
    for c in ctx.nodes("Constraint"):
        if c.get("constraint_type") != "torque":
            continue
        limit: Any = c.get("threshold")
        if limit is None:
            continue
        for t in ctx.nodes("Task"):
            obj = _task_objects(ctx, t.id)
            if obj is None or obj.get("weight_kg") is None:
                continue
            torque = round(float(obj.get("weight_kg")) * ARM_LENGTH_M, 3)
            if torque > limit:
                ctx.assert_(t.id, "over_torque", torque, evidence=[
                    f"图: {obj.id}.weight_kg = {obj.get('weight_kg')} kg × "
                    f"力臂 {ARM_LENGTH_M} m = {torque} N·m > 约束 {c.id} 阈值 {limit} N·m"])
            else:
                ctx.assert_(t.id, "torque_ok", torque, evidence=[
                    f"图: {obj.id}.weight_kg = {obj.get('weight_kg')} kg × "
                    f"力臂 {ARM_LENGTH_M} m = {torque} N·m ≤ 约束 {c.id} 阈值 {limit} N·m"])


def _load_constraint(ctx: RuleContext) -> None:
    """② 约束：负载超约束库 load 阈值 ⇒ 受约束（over_load）"""
    for c in ctx.nodes("Constraint"):
        if c.get("constraint_type") != "load":
            continue
        limit: Any = c.get("threshold")
        if limit is None:
            continue
        for t in ctx.nodes("Task"):
            obj = _task_objects(ctx, t.id)
            if obj is None or obj.get("weight_kg") is None:
                continue
            if obj.get("weight_kg") > limit:
                ctx.assert_(t.id, "over_load", float(obj.get("weight_kg")), evidence=[
                    f"图: {obj.id}.weight_kg = {obj.get('weight_kg')} kg > "
                    f"约束 {c.id} 阈值 {limit} kg"])


DOMAIN_RULES: List[RuleSpec] = [
    RuleSpec("has_handle⇒graspable", "有把手 ⇒ 可抓取（演绎）",
             category="deduction", priority=300, fire=_deduce_handle),
    RuleSpec("fragile⇒force_control", "易碎 ⇒ 需力控（演绎）",
             category="deduction", priority=300, fire=_deduce_fragile),
    RuleSpec("thread⇒screw", "有螺纹 ⇒ 需旋拧（演绎）",
             category="deduction", priority=300, fire=_deduce_thread),
    RuleSpec("surface⇒grip_factor", "表面状态 ⇒ 抓握力度系数（规则/归纳）",
             category="induction", priority=200, fire=_surface_grip_factor),
    RuleSpec("torque_constraint", "力矩=重量×力臂，超约束库 torque 阈值 ⇒ 受约束",
             category="constraint", priority=100, fire=_torque_constraint),
    RuleSpec("load_constraint", "负载超约束库 load 阈值 ⇒ 受约束",
             category="constraint", priority=100, fire=_load_constraint),
]
