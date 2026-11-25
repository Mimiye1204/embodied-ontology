# -*- coding: utf-8 -*-
"""校验层单元测试：SHACL L0（结构）+ L1（引用完整性/领域不变量）+ 加载器。"""
from __future__ import annotations

import copy

import pytest

from eo.graph import MemoryStore
from eo.graph.loader import load_entities
from eo.shacl import validate_entities


def _bad(fleet_entities, mutate):
    entities = copy.deepcopy(fleet_entities)
    mutate(entities)
    return entities


class TestL0Structural:
    def test_fleet_valid(self, fleet_entities):
        ok, report = validate_entities(fleet_entities)
        assert ok, report

    def test_rejects_negative_weight_and_enum(self, fleet_entities):
        def m(es):
            for e in es:
                if e["id"] == "eo:object/cup":
                    e["weight_kg"] = -1.0
                    e["surface"] = "wet"
        ok, _ = validate_entities(_bad(fleet_entities, m))
        assert not ok

    def test_rejects_unknown_property(self, fleet_entities):
        def m(es):
            for e in es:
                if e["id"] == "eo:object/cup":
                    e["wieght_kg"] = 0.3
        ok, _ = validate_entities(_bad(fleet_entities, m))
        assert not ok, "closed 形状应拦截拼写错误属性"


class TestL1Domain:
    def test_rejects_dangling_link(self, fleet_entities):
        def m(es):
            for e in es:
                if e["id"] == "eo:task/carry-cup":
                    e["requires_capability"] = ["eo:cap/nonexistent"]
        ok, _ = validate_entities(_bad(fleet_entities, m))
        assert not ok

    def test_rejects_duplicate_unique_key(self, fleet_entities):
        def m(es):
            for e in es:
                if e["id"] == "eo:robot/bx2":
                    e["serial"] = "TI5-T170C-001"
        ok, _ = validate_entities(_bad(fleet_entities, m))
        assert not ok

    def test_rejects_capability_without_provider(self, fleet_entities):
        def m(es):
            es.append({"id": "eo:cap/orphan", "type": "Capability", "label": "孤儿能力",
                       "code": "orphan", "created_at": "2026-11-20T08:00:00+08:00"})
        ok, _ = validate_entities(_bad(fleet_entities, m))
        assert not ok

    def test_rejects_unregistered_metric(self, fleet_entities):
        def m(es):
            es.append({"id": "eo:point/1", "type": "TelemetryPoint", "label": "坏测点",
                       "entity_ref": "eo:part/ti5/wrist", "metric_code": "unknown",
                       "value": 1.0, "time": "2026-11-24T10:00:00+08:00",
                       "created_at": "2026-11-24T10:00:00+08:00"})
        ok, _ = validate_entities(_bad(fleet_entities, m))
        assert not ok

    def test_rejects_foreign_fault_part(self, fleet_entities):
        def m(es):
            for e in es:
                if e["id"] == "eo:event/fault-001":
                    e["affects_bodypart"] = "eo:part/bx2/head"
        ok, _ = validate_entities(_bad(fleet_entities, m))
        assert not ok


class TestLoader:
    def test_rejects_unknown_type(self):
        with pytest.raises(ValueError):
            load_entities(MemoryStore(), [{"id": "eo:x", "type": "Nope"}])

    def test_rejects_abstract_type(self):
        with pytest.raises(ValueError):
            load_entities(MemoryStore(), [{"id": "eo:x", "type": "Entity"}])

    def test_rejects_dangling_link(self):
        store = MemoryStore()
        store.add_node("eo:t", "Task", {"label": "t"})
        with pytest.raises(ValueError):
            load_entities(store, [{"id": "eo:t2", "type": "Task",
                                   "requires_capability": ["eo:cap/missing"]}])
