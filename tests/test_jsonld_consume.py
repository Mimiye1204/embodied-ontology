# -*- coding: utf-8 -*-
"""JSON-LD 输出校验 + 仿真消费该数据的联调测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from eo.crud import OntologyCRUD
from eo.io import load_entities_file
from eo.jsonld import export_jsonld, from_jsonld_document, validate_jsonld, validate_jsonld_document
from eo.rules import DOMAIN_RULES
from eo.rules.framework import RuleEngine

ROOT = Path(__file__).resolve().parent.parent


def test_validate_jsonld_conforms(store):
    report = validate_jsonld(store)
    assert report.conforms, report


def test_validate_jsonld_rejects_bad_document():
    report = validate_jsonld_document({"@graph": []})   # 缺 @context
    assert not report.conforms
    assert any("context" in v.message for v in report.violations)


def test_roundtrip_feeds_rules(store):
    """导出 JSON-LD → 重导入 → 重建 CRUD → 规则引擎推出等价事实。"""
    entities = from_jsonld_document(export_jsonld(store))
    crud = OntologyCRUD()
    crud.load(entities)                                  # Gate A 通过 = 重导入数据合法
    eng = RuleEngine(crud.store)
    eng.add_rules(DOMAIN_RULES)
    eng.run()
    assert ("eo:task/carry-kettle", "over_torque") in eng.facts
    assert ("eo:object/cup-slip", "grip_factor") in eng.facts


def test_sim_consumes_jsonld_file(store, tmp_path):
    """落盘 .jsonld → load_entities_file 读回 → 建图与原始等价。"""
    p = tmp_path / "world.jsonld"
    p.write_text(json.dumps(export_jsonld(store), ensure_ascii=False), encoding="utf-8")
    entities = load_entities_file(str(p))
    crud = OntologyCRUD()
    crud.load(entities)
    assert {n.id for n in crud.store.nodes()} == {n.id for n in store.nodes()}


def test_sim_engine_consumes_jsonld(tmp_path):
    """端到端：仿真引擎直接用 JSON-LD 文档启动并跑场景。"""
    sys.path.insert(0, str(ROOT / "sim"))
    from eosim.engine import SimulationEngine      # noqa: E402
    from eosim.scenarios import SCENARIOS          # noqa: E402

    # 从 fleet 导出 JSON-LD（仿真世界的来源就是这份导出）
    from eo.graph import MemoryStore
    from eo.graph.loader import load_json_file
    store = load_json_file(MemoryStore(), str(ROOT / "examples" / "fleet.json"))
    p = tmp_path / "world.jsonld"
    p.write_text(json.dumps(export_jsonld(store), ensure_ascii=False), encoding="utf-8")

    eng = SimulationEngine(scenario=SCENARIOS["slip_loop"](),
                           data_path=str(p), outputs=str(tmp_path / "out"))
    eng.run(steps=6)
    assert eng.crud.get("eo:robot/ti5") is not None
    assert eng.crud.get("eo:task/carry-cup")["status"] == "executing"  # 场景 t=5 已下发
