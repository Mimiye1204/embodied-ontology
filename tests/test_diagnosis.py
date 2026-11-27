# -*- coding: utf-8 -*-
"""DTC 诊断接入（根因 + 级联告警 + 安全约束判断）单元测试。"""
from __future__ import annotations

import json
from pathlib import Path

from eo.diagnosis import receive_dtc

ROOT = Path(__file__).resolve().parent.parent


def _entities():
    fleet = json.loads((ROOT / "examples" / "fleet.json").read_text(encoding="utf-8"))
    faults = json.loads((ROOT / "examples" / "faults.json").read_text(encoding="utf-8"))
    return fleet + faults


def test_dtc_maps_to_mode():
    d = receive_dtc(_entities(), "C1001")
    assert d is not None
    assert d.fault_mode == "eo:faultmode/force-sensor-failure"


def test_dtc_unknown():
    assert receive_dtc(_entities(), "XXXX") is None


def test_dtc_root_cause_and_cascade():
    d = receive_dtc(_entities(), "C1001")
    assert "eo:part/ti5/six-axis-force" in d.root_causes
    fc = next(c for c in d.cascade if c.capability == "eo:cap/force-control")
    assert set(fc.tasks) == {"eo:task/grasp-egg", "eo:task/pinch-coin"}


def test_dtc_critical_safety():
    d = receive_dtc(_entities(), "C1001")   # force-sensor，critical
    assert d.safety.critical is True
    assert set(d.safety.blocked_tasks) == {"eo:task/grasp-egg", "eo:task/pinch-coin"}


def test_dtc_redundancy_aware():
    d = receive_dtc(_entities(), "C1003")   # arm-motor：push 由 base 冗余
    lost = {c.capability for c in d.cascade}
    assert "eo:cap/pour" in lost            # pour 只有 arm 提供 → 失效
    assert "eo:cap/push" not in lost        # push 有 base 冗余 → 不失效


def test_dtc_warning_no_capability_impact():
    d = receive_dtc(_entities(), "C1005")   # 腰部电机，warning，无能力
    assert d.safety.critical is False
    assert d.cascade == []                  # 不影响任何能力 → 无级联告警
