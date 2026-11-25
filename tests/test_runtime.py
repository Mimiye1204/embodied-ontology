# -*- coding: utf-8 -*-
"""时序层单元测试：属性绑定（物化读取）+ 时序存储（外键查询）。"""
from __future__ import annotations

from eo.timeseries import SqliteTelemetryStore
from eo.timeseries.binding import BindingRegistry


class TestTelemetryStore:
    def test_insert_query_last(self):
        ts = SqliteTelemetryStore(":memory:")
        ts.insert("eo:part/ti5/six-axis-force", "force_reading", 12.0, "2026-11-24T10:00:00")
        ts.insert("eo:part/ti5/six-axis-force", "force_reading", 4.0, "2026-11-24T10:00:01")
        ts.insert("eo:robot/ti5", "battery", 86.0, "2026-11-24T10:00:00")

        rows = ts.query(entity_ref="eo:part/ti5/six-axis-force", metric="force_reading")
        assert [r.value for r in rows] == [12.0, 4.0]
        assert ts.last("eo:part/ti5/six-axis-force", "force_reading").value == 4.0
        assert ts.last("eo:robot/ti5", "battery").value == 86.0
        assert len(ts.query()) == 3


class TestBinding:
    def test_read_and_snapshot(self, store):
        ts = SqliteTelemetryStore(":memory:")
        ts.insert("eo:robot/ti5", "battery", 86.0, "2026-11-24T10:00:00")
        ts.insert("eo:part/ti5/six-axis-force", "force_reading", 4.0, "2026-11-24T10:00:01")
        reg = BindingRegistry(store, ts)
        assert not reg.validate_bindings()
        assert reg.read("eo:robot/ti5", "current_battery") == 86.0
        assert reg.snapshot("eo:part/ti5/six-axis-force").get("current_force") == 4.0
        assert reg.read("eo:robot/ti5", "no_such_slot") is None

    def test_rejects_bad_binds_to(self, mutable_store):
        mutable_store.get_node("eo:metric/battery").properties["binds_to"] = "no_such_slot"
        reg = BindingRegistry(mutable_store, SqliteTelemetryStore(":memory:"))
        assert any("no_such_slot" in e for e in reg.validate_bindings())
