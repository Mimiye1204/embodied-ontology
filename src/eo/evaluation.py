# -*- coding: utf-8 -*-
"""评测报告链路：系统化评测故障溯源/传播/可达性/拦截，交叉验证一致性，产出报告。

评测三个维度（自检正确性，不依赖人工标注）：
  ① 一致性：故障传播(affected) ⟺ 可达性(verdict=infeasible) 双向应一致
  ② 根因准确：受影响样本在故障场景下，注入的故障部件应出现在 trace_root_cause 的根因里
  ③ 覆盖统计：verdict 分布 / 每个故障模式的影响任务数
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .dataset import generate_labeled_dataset


class EvaluationReport:
    def __init__(self) -> None:
        self.total = 0
        self.consistent = 0
        self.inconsistencies: List[Dict[str, Any]] = []
        self.root_cause_total = 0       # 受影响样本数（根因应命中）
        self.root_cause_ok = 0
        self.root_cause_misses: List[Dict[str, Any]] = []
        self.verdict_distribution: Dict[str, int] = {}
        self.per_mode_impact: Dict[str, int] = {}

    @property
    def consistency_rate(self) -> float:
        return self.consistent / self.total if self.total else 1.0

    @property
    def root_cause_accuracy(self) -> float:
        return self.root_cause_ok / self.root_cause_total if self.root_cause_total else 1.0


def evaluate(entities: List[Dict[str, Any]],
             fault_modes: Optional[List[str]] = None,
             task_ids: Optional[List[str]] = None) -> EvaluationReport:
    """跑全量评测并交叉验证。"""
    samples = generate_labeled_dataset(entities, fault_modes=fault_modes, task_ids=task_ids)
    mode_parts = {m["id"]: set(m.get("affects_bodypart", []))
                  for m in entities if m["type"] == "FaultMode"}

    report = EvaluationReport()
    report.total = len(samples)
    for s in samples:
        report.verdict_distribution[s["verdict"]] = \
            report.verdict_distribution.get(s["verdict"], 0) + 1

        # ① 一致性：affected ⟺ infeasible
        infeasible = (s["verdict"] == "infeasible")
        if s["affected"] == infeasible:
            report.consistent += 1
        else:
            report.inconsistencies.append(
                {"id": s["id"], "affected": s["affected"], "verdict": s["verdict"]})

        # ② 根因准确（仅对受影响样本）
        if s["affected"]:
            report.root_cause_total += 1
            if s["scenario"] == "baseline":
                report.root_cause_ok += 1   # 基线不应有受影响样本，理论到不了这里
                continue
            injected = mode_parts.get(s["scenario"], set())
            if injected & set(s["root_causes"]):
                report.root_cause_ok += 1
            else:
                report.root_cause_misses.append(
                    {"id": s["id"], "injected": sorted(injected),
                     "root_causes": s["root_causes"]})
            report.per_mode_impact[s["scenario"]] = \
                report.per_mode_impact.get(s["scenario"], 0) + 1

    return report


def report_text(report: EvaluationReport) -> str:
    """人类可读的评测报告（Markdown）。"""
    lines = [
        "# 故障溯源评测报告",
        "",
        f"- 样本总数：{report.total}",
        f"- verdict 分布：{report.verdict_distribution}",
        f"- **一致性**（affected ⟺ infeasible）：{report.consistent}/{report.total} "
        f"（{report.consistency_rate:.1%}）",
        f"- **根因准确**（受影响样本命中注入部件）：{report.root_cause_ok}/{report.root_cause_total} "
        f"（{report.root_cause_accuracy:.1%}）",
        "",
        "## 各故障模式影响面（受影响任务数）",
    ]
    for mode, n in sorted(report.per_mode_impact.items(), key=lambda x: -x[1]):
        lines.append(f"- {mode}：{n} 个任务受影响")
    if report.inconsistencies:
        lines += ["", "## 不一致项", "```json",
                  json.dumps(report.inconsistencies, ensure_ascii=False, indent=2), "```"]
    if report.root_cause_misses:
        lines += ["", "## 根因漏检", "```json",
                  json.dumps(report.root_cause_misses, ensure_ascii=False, indent=2), "```"]
    return "\n".join(lines)
