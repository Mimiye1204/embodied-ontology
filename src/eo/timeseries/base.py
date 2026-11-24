# -*- coding: utf-8 -*-
"""时序存储抽象：高频测点（关节角/力读数/电量/任务进度）落在时序库，
通过 entity_ref 外键关联到本体图里的实体（Node.id）。

动态库（时序）与静态库（本体图）分工：
  - 本体图回答「这台机器能干什么」；时序库回答「现在世界是什么样」。
  - 规则引擎读时序（当前状态）+ 图（能力/约束）做「当下能不能做」的判断。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TelemetryRow:
    entity_ref: str   # 外键 → 本体实体 id（如 eo:six_axis_force）
    metric: str       # 测点名（joint_angle / force_reading / battery / task_progress）
    value: float
    time: str         # ISO-8601 时间戳

    def __repr__(self) -> str:
        return f"TelemetryRow({self.entity_ref}, {self.metric}={self.value} @ {self.time})"


class TelemetryStore(ABC):
    @abstractmethod
    def insert(self, entity_ref: str, metric: str, value: float,
               time: Optional[str] = None) -> None: ...

    @abstractmethod
    def query(self, entity_ref: Optional[str] = None, metric: Optional[str] = None,
              start: Optional[str] = None, end: Optional[str] = None) -> List[TelemetryRow]: ...

    @abstractmethod
    def last(self, entity_ref: str, metric: str) -> Optional[TelemetryRow]: ...

    @abstractmethod
    def close(self) -> None: ...
