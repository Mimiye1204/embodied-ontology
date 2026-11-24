# -*- coding: utf-8 -*-
"""自研轻量规则引擎（正向链，固定点迭代 + 逐规则增量打印）。

设计目标（对应《本体系统调研》§6.1）：
  - 规则即数据：Rule 是普通对象，改一条立刻看到它多推出什么。
  - 增量打印：每次迭代记录「这条规则新推出了哪些事实」，便于快速调规则。
  - 证明可回看：trace 保留每条结论来自哪条规则。

Fact 统一为三元组 (subject, predicate, object)，与图节点/边对齐。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Set, Tuple

from ..graph.base import GraphStore

# (subject_id, predicate, value)
Fact = Tuple[str, str, Any]

# 规则触发函数：给定图与当前事实集，返回新推出的事实集
Fire = Callable[[GraphStore, Set[Fact]], Set[Fact]]


@dataclass
class Rule:
    name: str
    description: str
    fire: Fire

    def __call__(self, store: GraphStore, facts: Set[Fact]) -> Set[Fact]:
        return self.fire(store, facts)


@dataclass
class RoundTrace:
    rule_name: str
    description: str
    added: Set[Fact]


def forward_chain(
    store: GraphStore,
    rules: List[Rule],
    facts: Optional[Set[Fact]] = None,
    max_rounds: int = 20,
) -> Tuple[Set[Fact], List[RoundTrace]]:
    """反复触发规则直到没有新事实（不动点）。

    返回 (facts, trace)。trace 每一项记录某条规则在某一轮新推出的事实，
    空集的事实不会重复触发，保证收敛。
    """
    facts: Set[Fact] = set(facts or [])
    trace: List[RoundTrace] = []

    for _ in range(max_rounds):
        newly_total: Set[Fact] = set()
        for rule in rules:
            added = rule(store, facts) - facts
            if added:
                newly_total |= added
                trace.append(RoundTrace(rule.name, rule.description, added))
        if not newly_total:
            break
        facts |= newly_total

    return facts, trace


def nodes_of_type(store: GraphStore, type_name: str):
    """按 ObjectType 取全部实例。"""
    return [n for n in store.nodes() if n.type == type_name]
