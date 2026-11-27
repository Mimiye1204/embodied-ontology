# -*- coding: utf-8 -*-
"""硬件蓝图 → 本体 Object/Link/绑定 Action 自动生成 单元测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from eo.crud import ValidationError
from eo.hardware import build_from_blueprint, generate_entities, load_blueprint
from eo.rules import part_of_robot
from eo.shacl import validate_entities

BLUEPRINT = Path(__file__).resolve().parent.parent / "hardware" / "ti5.yaml"


def test_generate_and_gate_a():
    bp = load_blueprint(str(BLUEPRINT))
    entities = generate_entities(bp)
    ok, report = validate_entities(entities)
    assert ok, report


def test_generated_structure():
    crud, registry = build_from_blueprint(load_blueprint(str(BLUEPRINT)))
    types = {n.type for n in crud.store.nodes()}
    assert {"Robot", "BodyPart", "Capability", "Constraint"} <= types
    # 部件树（Link: part_of 链）：six-axis-force → wrist → arm → ti5
    assert part_of_robot(crud.store, "eo:part/ti5/arm/wrist/six-axis-force", "eo:robot/ti5")
    # 能力注册表（Object）与提供关系（Link: provides_capability）
    assert crud.get("eo:cap/power-grasp")["code"] == "power-grasp"
    assert crud.get("eo:cap/force-control")["label"] == "力控"
    # 约束 constrains 指向生成部件
    assert crud.get("eo:constraint/wrist-torque-limit")["constrains"] == "eo:part/ti5/arm/wrist"


def test_generated_actions_bound():
    crud, registry = build_from_blueprint(load_blueprint(str(BLUEPRINT)))
    assert len(registry.actions) == 6
    assert "task.dispatch" in registry.actions
    assert "fault.report" in registry.actions
    assert registry.actions["task.dispatch"].targets == ["Task"]


def test_undeclared_capability_rejected():
    bp = load_blueprint(str(BLUEPRINT))
    bp["parts"][0]["capabilities"] = ["nonexistent-cap"]
    with pytest.raises(ValueError, match="未声明的能力"):
        generate_entities(bp)


def test_missing_required_field_gate_a():
    bp = load_blueprint(str(BLUEPRINT))
    bp["parts"][1]["constraints"][0].pop("expression")  # 约束 expression 必填
    with pytest.raises(ValidationError):
        build_from_blueprint(bp)
