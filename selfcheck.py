# -*- coding: utf-8 -*-
"""本体底座整体自检入口：.venv/Scripts/python.exe selfcheck.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from eo.selfcheck import print_report, run_selfcheck  # noqa: E402

if __name__ == "__main__":
    data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples", "fleet.json")
    sys.exit(1 if print_report(run_selfcheck(data)) else 0)
