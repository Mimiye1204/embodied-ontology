# -*- coding: utf-8 -*-
"""场景基类：setup 一次性装配；tick 每秒被调用（t 从 1 开始）。"""
from __future__ import annotations


class Scenario:
    name: str = "base"
    description: str = ""
    duration: int = 12  # 仿真时长（秒/步）

    def setup(self, env) -> None:  # noqa: N802
        pass

    def tick(self, env, t: int) -> None:
        pass
