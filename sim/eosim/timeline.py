# -*- coding: utf-8 -*-
"""事件时间线：控制台 + JSONL 双输出。"""
from __future__ import annotations

import json
import os
from typing import Optional


class Timeline:
    def __init__(self, outputs_dir: str) -> None:
        os.makedirs(outputs_dir, exist_ok=True)
        self._path = os.path.join(outputs_dir, "timeline.jsonl")
        self._f = open(self._path, "w", encoding="utf-8")

    def event(self, t: int, source: str, msg: str) -> None:
        line = f"[t={t:02d}s] [{source}] {msg}"
        print(line)
        self._f.write(json.dumps({"t": t, "source": source, "msg": msg}, ensure_ascii=False) + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()
