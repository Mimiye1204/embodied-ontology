# -*- coding: utf-8 -*-
"""兼容层：旧 forward_chain 接口（tuple 事实集）包装规则引擎框架。

新代码直接用 eo.rules.framework.RuleEngine（证明链/优先级/动态属性/动作绑定）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Set, Tuple

from ..graph.base import GraphStore
from .framework import RuleContext, RuleEngine, RuleSpec, RoundTrace, Fact  # noqa: F401

# 旧版事实三元组类型（兼容）
Fact = Tuple[str, str, Any]  # noqa: F811

Fire = Callable[[GraphStore, Set[Fact]], Set[Fact]]


@dataclass
class Rule:
    """旧版规则对象（fire(store, facts)->set），由 forward_chain 包装成 RuleSpec。"""
    name: str
    description: str
    fire: Fire

    def __call__(self, store: GraphStore, facts: Set[Fact]) -> Set[Fact]:
        return self.fire(store, facts)


def _wrap_rule(rule) -> RuleSpec:
    if isinstance(rule, RuleSpec):
        return rule

    def fire(ctx: RuleContext) -> None:
        current = ctx.engine.fact_tuples()
        for s, p, v in rule.fire(ctx.store, current):
            ctx.assert_(s, p, v)

    return RuleSpec(name=rule.name, description=rule.description, fire=fire)


def forward_chain(
    store: GraphStore,
    rules: List,
    facts: Optional[Set[Tuple[str, str, Any]]] = None,
    max_rounds: int = 20,
) -> Tuple[Set[Tuple[str, str, Any]], List[RoundTrace]]:
    """正向链（兼容接口）：返回 (事实集, trace)。规则可为 RuleSpec 或旧 Rule。"""
    engine = RuleEngine(store)
    for r in rules:
        engine.add_rule(_wrap_rule(r))
    if facts:
        engine.seed(set(facts))
    engine.run(max_rounds)
    return engine.fact_tuples(), engine.trace


def nodes_of_type(store: GraphStore, type_name: str):
    """按 ObjectType 取全部实例。"""
    return [n for n in store.nodes() if n.type == type_name]
