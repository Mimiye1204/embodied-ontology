# -*- coding: utf-8 -*-
"""本体 ↔ 平台桥接单元测试（对齐 robot-dispatch 契约，docs/06）。"""
from __future__ import annotations

import json

from eo.platform import build_platform_robot, build_platform_telemetry
from eo.timeseries import SqliteTelemetryStore
from eo.timeseries.binding import BindingRegistry


def _ts():
    ts = SqliteTelemetryStore(":memory:")
    ts.insert("eo:robot/ti5", "battery", 86.0, "2026-11-25T10:00:00")
    ts.insert("eo:part/ti5/six-axis-force", "force_reading", 4.0, "2026-11-25T10:00:01")
    ts.insert("eo:part/ti5/wrist", "joint_angle", 32.0, "2026-11-25T10:00:01")
    return ts


def test_build_platform_robot(store):
    r = build_platform_robot(store, "eo:robot/ti5")
    assert r["model"] == "T170C 轮式人形"
    assert r["sn"] == "TI5-T170C-001"
    assert r["fw"] == "2.1.7.1"
    assert r["status"] == "online"


def test_telemetry_flat_fields(store):
    ts = _ts()
    b = BindingRegistry(store, ts)
    p = build_platform_telemetry(store, ts, b, "eo:robot/ti5")
    assert p["robot_id"] == "eo:robot/ti5"
    assert p["battery"] == 86          # 动态属性经时序绑定物化
    assert p["sn"] == "TI5-T170C-001"
    assert p["app_version"] == "2.1.7.1"
    assert p["status"] == "online"


def test_telemetry_ti5_packs_metrics(store):
    ts = _ts()
    b = BindingRegistry(store, ts)
    p = build_platform_telemetry(store, ts, b, "eo:robot/ti5")
    ti5 = json.loads(p["ti5"])
    assert ti5["ontology_version"] == "1.1.0"
    assert ti5["metrics"]["eo:part/ti5/six-axis-force"]["force_reading"] == 4.0
    assert ti5["metrics"]["eo:part/ti5/wrist"]["joint_angle"] == 32.0
    assert ti5["metrics"]["eo:robot/ti5"]["battery"] == 86.0


def test_telemetry_unknown_robot(store):
    ts = _ts()
    b = BindingRegistry(store, ts)
    assert build_platform_telemetry(store, ts, b, "eo:robot/ghost") is None
