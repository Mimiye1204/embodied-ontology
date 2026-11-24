# -*- coding: utf-8 -*-
"""SQLite 时序存储（本地回退实现，接口与 TimescaleTelemetryStore 一致）。

本机无 PostgreSQL/TimescaleDB 时用它跑通全链路 demo；
生产切换到 TimescaleTelemetryStore 时业务代码零改动。
"""
from __future__ import annotations

import sqlite3
from typing import List, Optional

from .base import TelemetryRow, TelemetryStore, now_iso


class SqliteTelemetryStore(TelemetryStore):
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS telemetry ("
            "  time TEXT NOT NULL,"
            "  entity_ref TEXT NOT NULL,"  # 外键 → 本体实体 id（逻辑外键）
            "  metric TEXT NOT NULL,"
            "  value REAL NOT NULL"
            ")"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_entity_time "
            "ON telemetry(entity_ref, time)"
        )

    def insert(self, entity_ref: str, metric: str, value: float,
               time: Optional[str] = None) -> None:
        self._conn.execute(
            "INSERT INTO telemetry(time, entity_ref, metric, value) VALUES (?, ?, ?, ?)",
            (time or now_iso(), entity_ref, metric, float(value)),
        )
        self._conn.commit()

    def query(self, entity_ref: Optional[str] = None, metric: Optional[str] = None,
              start: Optional[str] = None, end: Optional[str] = None) -> List[TelemetryRow]:
        sql = "SELECT entity_ref, metric, value, time FROM telemetry WHERE 1=1"
        args: list = []
        if entity_ref is not None:
            sql += " AND entity_ref = ?"; args.append(entity_ref)
        if metric is not None:
            sql += " AND metric = ?"; args.append(metric)
        if start is not None:
            sql += " AND time >= ?"; args.append(start)
        if end is not None:
            sql += " AND time <= ?"; args.append(end)
        sql += " ORDER BY time"
        rows = self._conn.execute(sql, args).fetchall()
        return [TelemetryRow(entity_ref=r[0], metric=r[1], value=r[2], time=r[3])
                for r in rows]

    def last(self, entity_ref: str, metric: str) -> Optional[TelemetryRow]:
        rows = self._conn.execute(
            "SELECT entity_ref, metric, value, time FROM telemetry "
            "WHERE entity_ref = ? AND metric = ? ORDER BY time DESC LIMIT 1",
            (entity_ref, metric),
        ).fetchall()
        if not rows:
            return None
        r = rows[0]
        return TelemetryRow(entity_ref=r[0], metric=r[1], value=r[2], time=r[3])

    def close(self) -> None:
        self._conn.close()
