# -*- coding: utf-8 -*-
"""单元测试入口（等价于 pytest tests/，保留旧习惯）。

用法：
  .venv/Scripts/python.exe -m pytest tests/ -v
  .venv/Scripts/python.exe tests/run_tests.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
sys.exit(pytest.main([str(TESTS_DIR), "-v"]))
