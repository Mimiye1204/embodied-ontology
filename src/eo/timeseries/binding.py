# -*- coding: utf-8 -*-
"""时序属性绑定（docs/04 §1 设计落地）。

模型：TelemetryMetric 注册表上的 binds_to / aggregation / window_seconds 声明
「测点 → 本体动态属性」的绑定；本模块按声明从时序库聚合读取，
把动态属性物化成可查询值（不落图库——动态值永远活在时序库，按需计算）。

- BindingRegistry：从本体图构建绑定表 + 绑定合法性校验（binds_to 必须是
  measures 目标类上的槽）
- 聚合算子：last / avg / min / max / count / rate（对应 Schema 枚举 MetricAggregation）
- 规则引擎通过 RuleContext.dynamic(entity, slot) 消费（eo/rules/framework.py）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from ..graph.base import GraphStore
from ..schema import class_slots
from .base import TelemetryStore


@dataclass
class MetricBinding:
    metric_code: str
    entity_ref: str          # measures 目标（测点归属实体）
    binds_to: str            # 物化的动态属性槽
    aggregation: str         # last/avg/min/max/count/rate
    window_seconds: float    # 0 = 全量窗口


class BindingRegistry:
    """测点注册表 → 绑定表；提供动态属性读取。"""

    def __init__(self, store: GraphStore, telemetry: TelemetryStore) -> None:
        self.store = store
        self.telemetry = telemetry
        self.bindings: List[MetricBinding] = []
        for n in store.nodes():
            if n.type != "TelemetryMetric":
                continue
            targets = store.out_neighbors(n.id, "measures")
            if not targets:
                continue
            self.bindings.append(MetricBinding(
                metric_code=n.get("metric_code", ""),
                entity_ref=targets[0].id,
                binds_to=n.get("binds_to") or "",
                aggregation=n.get("aggregation") or "last",
                window_seconds=float(n.get("window_seconds") or 0.0),
            ))

    # ---------------------------------------------------------------- 校验
    def validate_bindings(self) -> List[str]:
        """绑定合法性：binds_to 必须是 measures 目标类上的槽（动态属性）。"""
        errors: List[str] = []
        for b in self.bindings:
            target = self.store.get_node(b.entity_ref)
            if target is None:
                errors.append(f"{b.metric_code}：measures 目标 {b.entity_ref} 不存在")
                continue
            if not b.binds_to:
                continue  # 未声明绑定 = 纯时序测点，合法
            if b.binds_to not in class_slots(target.type):
                errors.append(
                    f"{b.metric_code}：binds_to '{b.binds_to}' 不是 {target.type} "
                    f"的槽（{target.id}）")
            if b.aggregation not in ("last", "avg", "min", "max", "count", "rate"):
                errors.append(f"{b.metric_code}：未知聚合算子 '{b.aggregation}'")
        return errors

    # ---------------------------------------------------------------- 读取
    def binding_of(self, entity_ref: str, slot: str) -> Optional[MetricBinding]:
        for b in self.bindings:
            if b.entity_ref == entity_ref and b.binds_to == slot:
                return b
        return None

    def read(self, entity_ref: str, slot: str) -> Optional[float]:
        """读动态属性：按绑定声明从时序库聚合。无绑定/无数据 → None。"""
        b = self.binding_of(entity_ref, slot)
        if b is None:
            return None
        start = None
        if b.window_seconds > 0:
            # 窗口起点：用最新样本时间回推
            latest = self.telemetry.last(entity_ref, b.metric_code)
            if latest is None:
                return None
            from datetime import datetime, timedelta
            try:
                t0 = datetime.fromisoformat(latest.time) - timedelta(seconds=b.window_seconds)
                start = t0.isoformat()
            except ValueError:
                start = None
        rows = self.telemetry.query(entity_ref=entity_ref, metric=b.metric_code, start=start)
        if not rows:
            return None
        values = [r.value for r in rows]
        if b.aggregation == "last":
            return values[-1]
        if b.aggregation == "avg":
            return round(sum(values) / len(values), 4)
        if b.aggregation == "min":
            return min(values)
        if b.aggregation == "max":
            return max(values)
        if b.aggregation == "count":
            return float(len(values))
        if b.aggregation == "rate":
            if len(values) < 2 or b.window_seconds <= 0:
                return None
            return round((values[-1] - values[0]) / b.window_seconds, 4)
        return None

    def snapshot(self, entity_ref: str) -> Dict[str, float]:
        """实体全部动态属性的当前物化值。"""
        out: Dict[str, float] = {}
        for b in self.bindings:
            if b.entity_ref != entity_ref or not b.binds_to:
                continue
            v = self.read(entity_ref, b.binds_to)
            if v is not None:
                out[b.binds_to] = v
        return out
