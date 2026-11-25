# -*- coding: utf-8 -*-
"""pytest 共享夹具：编队数据 / 图存储 / CRUD / 规则引擎。"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from eo.crud import OntologyCRUD           # noqa: E402
from eo.graph import MemoryStore           # noqa: E402
from eo.graph.loader import load_json_file # noqa: E402
from eo.rules import DOMAIN_RULES          # noqa: E402
from eo.rules.framework import RuleEngine  # noqa: E402

DATA = ROOT / "examples" / "fleet.json"


@pytest.fixture(scope="session")
def fleet_entities():
    """编队实体清单（ABox，58 实体，只读）。"""
    return json.loads(DATA.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def store():
    """图存储（内存实现，只读），已从 fleet.json 建图。"""
    return load_json_file(MemoryStore(), str(DATA))


@pytest.fixture
def mutable_store():
    """可改写的图存储副本（会改健康/绑定的测试用，避免污染 session 级 store）。"""
    return load_json_file(MemoryStore(), str(DATA))


@pytest.fixture
def crud(fleet_entities):
    """CRUD 唯一写路径（Gate A）；函数级隔离，从只读清单深拷贝。"""
    c = OntologyCRUD()
    c.load(copy.deepcopy(fleet_entities))
    return c


@pytest.fixture(scope="session")
def engine(store):
    """规则引擎（已加载领域规则并跑完固定点，只读）。"""
    e = RuleEngine(store)
    e.add_rules(DOMAIN_RULES)
    e.run()
    return e
