# -*- coding: utf-8 -*-
"""本体 CRUD CLI 入口（项目根）：.venv/Scripts/python.exe cli.py <命令>"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from eo.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
