# -*- coding: utf-8 -*-
"""TimescaleDB 时序存储（生产实现，psycopg 3，惰性导入）。

表结构见 ddl/timescale_schema.sql（hypertable + 实体/时间复合索引）。
entity_ref 是「逻辑外键」：指向本体图（Neo4j）中的实体 id，
若实体库也落在 PostgreSQL 则可改为 REFERENCES 真外键（见 ddl 注释）。
"""
from __future__ import annotations

from typing import List, Optional

from .base import TelemetryRow, TelemetryStore, now_iso


class TimescaleTelemetryStore(TelemetryStore):
    def __init__(self, conninfo: str = "postgresql://postgres:postgres@localhost:5432/robot") -> None:
        import psycopg  # 惰性导入

        self._conn = psycopg.connect(conninfo, autocommit=True)

    def insert(self, entity_ref: str, metric: str, value: float,
               time: Optional[str] = None) -> None:
        self._conn.execute(
            "INSERT INTO telemetry(time, entity_ref, metric, value) VALUES (%s, %s, %s, %s)",
            (time or now_iso(), entity_ref, metric, float(value)),
        )

    def query(self, entity_ref: Optional[str] = None, metric: Optional[str] = None,
              start: Optional[str] = None, end: Optional[str] = None) -> List[TelemetryRow]:
        sql = "SELECT entity_ref, metric, value, time FROM telemetry WHERE 1=1"
        args: list = []
        if entity_ref is not None:
            sql += " AND entity_ref = %s"; args.append(entity_ref)
        if metric is not None:
            sql += " AND metric = %s"; args.append(metric)
        if start is not None:
            sql += " AND time >= %s"; args.append(start)
        if end is not None:
            sql += " AND time <= %s"; args.append(end)
        sql += " ORDER BY time"
        rows = self._conn.execute(sql, args).fetchall()
        return [TelemetryRow(entity_ref=r[0], metric=r[1], value=float(r[2]), time=str(r[3]))
                for r in rows]

    def last(self, entity_ref: str, metric: str) -> Optional[TelemetryRow]:
        rows = self._conn.execute(
            "SELECT entity_ref, metric, value, time FROM telemetry "
            "WHERE entity_ref = %s AND metric = %s ORDER BY time DESC LIMIT 1",
            (entity_ref, metric),
        ).fetchall()
        if not rows:
            return None
        r = rows[0]
        return TelemetryRow(entity_ref=r[0], metric=r[1], value=float(r[2]), time=str(r[3]))

    def close(self) -> None:
        self._conn.close()
