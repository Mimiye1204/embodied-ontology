# -*- coding: utf-8 -*-
"""仿真时钟：t（秒）↔ ISO-8601 时间戳。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 11, 24, 10, 0, 0, tzinfo=timezone(timedelta(hours=8)))


def iso(t: int) -> str:
    """仿真时钟 t（秒）→ ISO-8601 时间戳。"""
    return (T0 + timedelta(seconds=t)).isoformat()
