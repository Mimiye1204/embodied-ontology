# -*- coding: utf-8 -*-
"""故障溯源评测报告链路 单元测试。"""
from __future__ import annotations

import json
from pathlib import Path

from eo.evaluation import evaluate, report_text

ROOT = Path(__file__).resolve().parent.parent


def _entities():
    fleet = json.loads((ROOT / "examples" / "fleet.json").read_text(encoding="utf-8"))
    faults = json.loads((ROOT / "examples" / "faults.json").read_text(encoding="utf-8"))
    return fleet + faults


def test_evaluation_fully_consistent():
    report = evaluate(_entities())
    assert report.total > 0
    assert report.consistency_rate == 1.0, f"不一致项：{report.inconsistencies}"
    assert report.root_cause_accuracy == 1.0, f"漏检：{report.root_cause_misses}"


def test_verdict_distribution_has_both():
    report = evaluate(_entities())
    assert "feasible" in report.verdict_distribution
    assert "infeasible" in report.verdict_distribution


def test_per_mode_impact():
    report = evaluate(_entities())
    # 六维力失效 → 抓鸡蛋/捏硬币受影响
    assert report.per_mode_impact["eo:faultmode/force-sensor-failure"] == 2


def test_report_text_structure():
    report = evaluate(_entities())
    text = report_text(report)
    assert "一致性" in text
    assert "根因准确" in text
    assert "影响面" in text
