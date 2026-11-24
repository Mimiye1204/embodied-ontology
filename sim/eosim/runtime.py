# -*- coding: utf-8 -*-
"""机器人运行时模拟：按 TelemetryMetric 测点注册表生成时序数据。

生产对应物：真实机器人遥测（关节 1Hz / 六维力 100Hz / 电量），
写入同一个 TelemetryStore 接口（SQLite 本地 / TimescaleDB 生产）。
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

from .clock import iso


class RobotRuntime:
    def __init__(self, engine, seed: int = 0) -> None:
        self.engine = engine
        self.rnd = engine.random
        self.metrics = [n for n in engine.store.nodes() if n.type == "TelemetryMetric"]
        self.anomalies: Dict[str, Dict[str, Any]] = {}

    def set_anomaly(self, metric_code: str, profile: Dict[str, Any]) -> None:
        """给测点挂异常剖面。profile 例：{"type":"decay","from":3,"to":7,"start":12.0,"end":4.0}"""
        self.anomalies[metric_code] = profile

    def tick(self, t: int) -> None:
        for m in self.metrics:
            targets = self.engine.store.out_neighbors(m.id, "measures")
            if not targets:
                continue
            code = m.get("metric_code")
            value = self._value(code, t)
            if value is None:
                continue  # 事件驱动型测点（如 task_progress）由调度器显式写
            self.engine.telemetry.insert(targets[0].id, code, value, iso(t))

    def _value(self, code: str, t: int) -> Optional[float]:
        profile = self.anomalies.get(code)
        if profile:
            if profile.get("from", 0) <= t <= profile.get("to", t + 1):
                if profile["type"] == "decay":
                    span = max(1, profile["to"] - profile["from"])
                    k = (t - profile["from"]) / span
                    return round(profile["start"] + (profile["end"] - profile["start"]) * k, 2)
            if profile.get("hold") and t > profile["to"]:
                return profile["end"]  # 异常后保持终值（滑移不自动恢复）

        if code == "force_reading":
            return round(12.0 + self.rnd.uniform(-0.4, 0.4), 2)
        if code == "joint_angle":
            return round(30.0 + 5.0 * math.sin(t / 3), 2)
        if code == "battery":
            return round(max(60.0, 86.0 - t * 0.02), 2)
        return None  # task_progress 等事件驱动测点

    # ---------------------------------------------------------------- 检测
    def detect_drop(self, entity_ref: str, metric: str, threshold: float = 0.5):
        """读时序库做异常检测：末值较初值骤降超过 threshold 比例则告警。"""
        rows = self.engine.telemetry.query(entity_ref=entity_ref, metric=metric)
        if len(rows) < 2:
            return None
        first, last = rows[0].value, rows[-1].value
        if first <= 0:
            return None
        ratio = last / first
        if ratio < threshold:
            return {
                "first": first, "last": last,
                "drop_pct": round((1 - ratio) * 100),
            }
        return None
