# -*- coding: utf-8 -*-
"""带语义标签数据集生成 单元测试。"""
from __future__ import annotations

import json
from pathlib import Path

from eo.dataset import export_dataset, generate_labeled_dataset

ROOT = Path(__file__).resolve().parent.parent


def _entities():
    fleet = json.loads((ROOT / "examples" / "fleet.json").read_text(encoding="utf-8"))
    faults = json.loads((ROOT / "examples" / "faults.json").read_text(encoding="utf-8"))
    return fleet + faults


def test_dataset_generates_all_scenarios():
    samples = generate_labeled_dataset(_entities())
    n_tasks = sum(1 for e in _entities() if e["type"] == "Task")
    n_modes = sum(1 for e in _entities() if e["type"] == "FaultMode")
    assert len(samples) == n_tasks * (1 + n_modes)  # 基线 + 每个故障模式


def test_baseline_is_feasible():
    samples = generate_labeled_dataset(_entities(), task_ids=["eo:task/grasp-egg"])
    baseline = next(s for s in samples if s["scenario"] == "baseline")
    assert baseline["verdict"] == "feasible"
    assert baseline["affected"] is False
    assert baseline["lost_capabilities"] == []


def test_fault_scenario_labels():
    samples = generate_labeled_dataset(_entities(), task_ids=["eo:task/grasp-egg"])
    s = next(x for x in samples if x["scenario"] == "eo:faultmode/force-sensor-failure")
    assert s["verdict"] == "infeasible"
    assert s["affected"] is True
    assert "eo:cap/force-control" in s["lost_capabilities"]
    # 语义标签：任务/物体/场景都有中文标签
    assert s["task_label"] == "抓鸡蛋"
    assert s["object_label"] == "鸡蛋"
    assert "六维力" in s["scenario_label"]
    assert set(s["required_capabilities"]) == {"eo:cap/power-grasp", "eo:cap/force-control"}


def test_interception_in_sample():
    samples = generate_labeled_dataset(_entities(), task_ids=["eo:task/push-box"])
    baseline = next(s for s in samples if s["scenario"] == "baseline")
    assert {"torque", "load", "gripper"} <= set(baseline["interceptions"])


def test_export_jsonl():
    samples = generate_labeled_dataset(_entities(), task_ids=["eo:task/carry-cup"])
    text = export_dataset(samples, format="jsonl")
    assert text.count("\n") == len(samples) - 1
    assert all("semantic" not in line for line in text.splitlines())  # 无污染
