# -*- coding: utf-8 -*-
"""故障本体样本 + 故障传播规则（冗余感知）单元测试。"""
from __future__ import annotations

import json
from pathlib import Path

from eo.actions import build_registry
from eo.rules import DOMAIN_RULES, FAULT_RULES
from eo.rules.framework import RuleEngine
from eo.shacl import validate_entities

ROOT = Path(__file__).resolve().parent.parent


def _entities():
    fleet = json.loads((ROOT / "examples" / "fleet.json").read_text(encoding="utf-8"))
    faults = json.loads((ROOT / "examples" / "faults.json").read_text(encoding="utf-8"))
    return fleet + faults


def _run(store):
    eng = RuleEngine(store)
    eng.add_rules(DOMAIN_RULES + FAULT_RULES)
    eng.run()
    return eng


def test_fault_samples_valid():
    ok, report = validate_entities(_entities())
    assert ok, report


def test_part_fault_propagation(mutable_store):
    mutable_store.get_node("eo:part/ti5/six-axis-force").properties["health"] = "fault"
    eng = _run(mutable_store)
    assert ("eo:cap/force-control", "lost") in eng.facts
    assert ("eo:task/grasp-egg", "affected_by_fault") in eng.facts


def test_redundancy_aware(mutable_store):
    """arm 故障：pour 只有 arm 提供 → 失效；push 由 base 冗余提供 → 不失效。"""
    mutable_store.get_node("eo:part/ti5/arm").properties["health"] = "fault"
    eng = _run(mutable_store)
    assert ("eo:cap/pour", "lost") in eng.facts
    assert ("eo:cap/push", "lost") not in eng.facts          # 冗余：base 仍健康
    assert ("eo:task/push-box", "affected_by_fault") not in eng.facts
    assert ("eo:task/pour-water", "affected_by_fault") in eng.facts


def test_proof_chain(mutable_store):
    mutable_store.get_node("eo:part/ti5/six-axis-force").properties["health"] = "fault"
    eng = _run(mutable_store)
    assert "six-axis-force" in eng.explain("eo:cap/force-control", "lost")


def test_fault_report_action_propagates(crud):
    reg = build_registry(crud)
    result = reg.execute("fault.report", actor="test",
                         mode_id="eo:faultmode/force-sensor-failure")
    assert result.ok
    eng = _run(crud.store)   # fault.report 已把 six-axis-force 置 fault
    assert ("eo:cap/force-control", "lost") in eng.facts
    assert ("eo:task/grasp-egg", "affected_by_fault") in eng.facts
