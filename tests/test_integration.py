# -*- coding: utf-8 -*-
"""集成自检（CI 入口）：跑完整联调流水线，任一段失败即失败。"""
from __future__ import annotations

from pathlib import Path

from eo.selfcheck import run_selfcheck

DATA = Path(__file__).resolve().parent.parent / "examples" / "fleet.json"


def test_selfcheck_all_pass():
    results = run_selfcheck(str(DATA))
    failures = [r for r in results if not r.passed]
    assert not failures, "\n".join(f"{r.name}: {r.detail}" for r in failures)
