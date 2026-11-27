# -*- coding: utf-8 -*-
"""故障本体样本 + 故障传播规则（RuleSpec）单元测试。"""
from __future__ import annotations

import json
from pathlib import Path

from eo.crud import OntologyCRUD
from eo.rules import DOMAIN_RULES, FAULT_RULES
from eo.rules.framework import RuleEngine
from eo.shacl import validate_entities

ROOT = Path(__file__).resolve().parent.parent


def _world():
    fleet = json.loads((ROOT / "examples" / "fleet.json").read_text(encoding="utf-8"))
    faults = json.loads((ROOT / "examples" / "faults.json").read_text(encoding="utf-8"))
    return fleet + faults


def _engine():
    crud = OntologyCRUD()
    crud.load(_world())
    eng = RuleEngine(crud.store)
    eng.add_rules(DOMAIN_RULES + FAULT_RULES)
    eng.run()
    return crud, eng


def test_fault_samples_valid():
    ok, report = validate_entities(_world())
    assert ok, report


def test_event_propagation_rules():
    _, eng = _engine()
    # 活跃故障事件 → 模式 → 能力失效
    for cap in ("force-control", "power-grasp", "pinch", "press", "locomotion", "push"):
        assert eng.facts.get((f"eo:cap/{cap}", "lost")), f"{cap} 应失效"
    # resolved 事件不传播：arm-motor 已恢复 → pour 未失效
    assert ("eo:cap/pour", "lost") not in eng.facts
    # 级联：失效能力 → 依赖任务受影响
    assert ("eo:task/grasp-egg", "affected_by_fault") in eng.facts
    assert ("eo:task/carry-cup", "affected_by_fault") in eng.facts
    # 依赖隔离：sitting 未故障 → 坐下不受影响
    assert ("eo:task/sit-down", "affected_by_fault") not in eng.facts


def test_part_fault_rule():
    crud, _ = _engine()
    # 部件故障路径（直接置 health=fault，不经事件）
    crud.set_property("eo:part/ti5/six-axis-force", "health", "fault")
    eng = RuleEngine(crud.store)
    eng.add_rules(DOMAIN_RULES + FAULT_RULES)
    eng.run()
    assert ("eo:cap/force-control", "lost") in eng.facts


def test_fault_proof_chain():
    _, eng = _engine()
    # 能力失效的证明链：追溯到事件/模式
    assert "fault-001" in eng.explain("eo:cap/force-control", "lost")
    # 任务受影响的证明链：追溯到失效能力
    assert "force-control" in eng.explain("eo:task/grasp-egg", "affected_by_fault")
