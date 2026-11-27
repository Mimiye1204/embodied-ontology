# -*- coding: utf-8 -*-
"""DTC 诊断接入：接收 DTC → 图推理 → 根因 + 级联告警 + 安全约束判断（PHM 管线）。

- receive_dtc：DTC 码 → 故障模式（FaultMode.dtc_code）→ 注入故障 → 图推理
  - 根因：trace_root_cause（受影响任务的因果链）
  - 级联告警：失效能力 → 依赖任务（fault propagation 规则，冗余感知）
  - 安全约束判断：severity=critical → 阻断受影响任务；否则降级告警
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .dataset import _build_store
from .reasoning import trace_root_cause
from .rules import DOMAIN_RULES, FAULT_RULES
from .rules.framework import RuleEngine


@dataclass
class CascadeAlarm:
    capability: str                 # 失效能力 id
    tasks: List[str] = field(default_factory=list)   # 依赖该能力的任务（应告警）


@dataclass
class SafetyJudgment:
    critical: bool
    blocked_tasks: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


@dataclass
class DtcDiagnosis:
    dtc: str
    fault_mode: str
    mode_label: str
    severity: str
    affected_parts: List[str] = field(default_factory=list)
    root_causes: List[str] = field(default_factory=list)
    cascade: List[CascadeAlarm] = field(default_factory=list)
    safety: SafetyJudgment = field(default_factory=SafetyJudgment)


def receive_dtc(entities: List[Dict[str, Any]], dtc_code: str) -> Optional[DtcDiagnosis]:
    """接收一个 DTC，跑完整诊断推理。未匹配到故障模式返回 None。"""
    mode = next((e for e in entities
                 if e["type"] == "FaultMode" and e.get("dtc_code") == dtc_code), None)
    if mode is None:
        return None

    # 干净副本 + 注入该模式故障（受影响部件 health=fault）
    store = _build_store(entities, mode)

    # 图推理：故障传播规则（冗余感知）
    eng = RuleEngine(store)
    eng.add_rules(DOMAIN_RULES + FAULT_RULES)
    eng.run()

    lost = sorted(f.s for f in eng.facts.values() if f.p == "lost")
    affected = sorted(f.s for f in eng.facts.values() if f.p == "affected_by_fault")

    # 根因：对每个受影响任务溯源，收集根因实体
    root_causes: set = set()
    for task_id in affected:
        for c in trace_root_cause(store, task_id).causes:
            root_causes.add(c.entity)

    # 级联告警：失效能力 → 依赖任务
    cascade = [
        CascadeAlarm(capability=cap_id,
                     tasks=sorted(t.id for t in store.in_neighbors(cap_id, "requires_capability")))
        for cap_id in lost
    ]

    # 安全约束判断
    severity = mode.get("default_severity", "warning")
    critical = severity == "critical"
    reasons = [
        f"严重故障（{severity}）→ 阻断 {len(affected)} 个任务执行" if critical
        else f"告警级故障（{severity}）→ {len(affected)} 个任务受影响，建议降级运行",
    ]

    return DtcDiagnosis(
        dtc=dtc_code,
        fault_mode=mode["id"],
        mode_label=mode.get("label", mode["id"]),
        severity=severity,
        affected_parts=list(mode.get("affects_bodypart", [])),
        root_causes=sorted(root_causes),
        cascade=cascade,
        safety=SafetyJudgment(critical=critical, blocked_tasks=affected, reasons=reasons),
    )


def diagnosis_text(d: DtcDiagnosis) -> str:
    """人类可读诊断报告。"""
    if d is None:
        return "未匹配到该 DTC 的故障模式"
    lines = [
        f"DTC {d.dtc} → 故障模式 {d.fault_mode}（{d.mode_label}）severity={d.severity}",
        f"受影响部件：{d.affected_parts}",
        f"根因：{d.root_causes}",
    ]
    lines.append("级联告警：")
    for c in d.cascade:
        lines.append(f"  ✗ {c.capability} 失效 → 告警任务 {c.tasks}")
    lines.append("安全约束判断：")
    for r in d.safety.reasons:
        lines.append(f"  {'⛔' if d.safety.critical else '⚠'} {r}")
    lines.append(f"  阻断任务：{d.safety.blocked_tasks}")
    return "\n".join(lines)
