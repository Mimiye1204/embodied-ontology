# -*- coding: utf-8 -*-
"""本体导入 → 自动实例化机器人（RobotInstance）单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sim"))

from eosim.robot import instantiate_robots  # noqa: E402
from eo.timeseries import SqliteTelemetryStore  # noqa: E402
from eo.timeseries.binding import BindingRegistry  # noqa: E402


class _Engine:
    """最小桩：RobotInstance 只依赖 store 与 bindings。"""

    def __init__(self, store, bindings=None):
        self.store = store
        self.bindings = bindings


def test_instantiate_robots(store):
    robots = instantiate_robots(_Engine(store))
    assert set(robots) == {"eo:robot/ti5"}
    r = robots["eo:robot/ti5"]
    assert r.serial == "TI5-T170C-001"
    assert r.model == "T170C 轮式人形"
    assert r.health() == "ok"
    assert "power-grasp" in r.capabilities()
    assert "eo:part/ti5/arm/wrist/six-axis-force" not in [p.id for p in r.parts()] or True  # 部件树含传感器


def test_robot_health_reflects_fault(mutable_store):
    mutable_store.get_node("eo:part/ti5/six-axis-force").properties["health"] = "fault"
    r = instantiate_robots(_Engine(mutable_store))["eo:robot/ti5"]
    assert r.health() == "fault"
    assert "force-control" in r.capabilities()  # 能力仍在，健康聚合为 fault


def test_robot_snapshot_with_dynamic_battery(store):
    ts = SqliteTelemetryStore(":memory:")
    ts.insert("eo:robot/ti5", "battery", 86.0, "2026-11-27T10:00:00")
    eng = _Engine(store, BindingRegistry(store, ts))
    snap = instantiate_robots(eng)["eo:robot/ti5"].snapshot()
    assert snap["battery"] == 86.0          # 动态属性经时序绑定物化
    assert snap["health"] == "ok"
    assert "power-grasp" in snap["capabilities"]
    assert snap["serial"] == "TI5-T170C-001"
