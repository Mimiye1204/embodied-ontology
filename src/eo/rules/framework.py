# -*- coding: utf-8 -*-
"""自研轻量规则引擎框架（L2 计算层，docs/04 §2 设计落地）。

- RuleSpec：规则即数据 —— 分类（演绎/约束/归纳/监测）、优先级、触发函数、
  声明式动作绑定（断言新事实时自动触发本体写回动作）
- RuleContext：统一上下文 —— 图（节点/Link）、事实（带证明链）、
  时序动态属性（BindingRegistry）、动作触发、注记输出
- RuleEngine：正向链固定点 + 逐规则增量 trace + 优先级序 + 证明链回溯
  （explain() 回答「为什么推出这个结论」，调研 §6.5 的证明树要求）

兼容层：engine.py 的 forward_chain() 保持旧接口（tuple 事实集），
旧 Rule 对象自动包装成 RuleSpec。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..graph.base import GraphStore
from ..timeseries.binding import BindingRegistry

FactKey = Tuple[str, str]  # (subject, predicate)


@dataclass
class Fact:
    s: str
    p: str
    v: Any
    source: str                    # 产出规则名（seed 事实为 "seed"）
    round: int                     # 第几轮推出
    evidence: List[str] = field(default_factory=list)  # 证明链

    def as_tuple(self) -> Tuple[str, str, Any]:
        return (self.s, self.p, self.v)


@dataclass
class RuleSpec:
    name: str
    description: str
    category: str = "deduction"    # deduction / constraint / induction / monitoring
    priority: int = 100            # 越大越先触发（同轮内确定性排序）
    fire: Callable[["RuleContext"], None] = None
    actions: List[Dict[str, Any]] = field(default_factory=list)
    # 声明式动作绑定：[{"action": name, "params": {...支持 {s}/{p}/{v} 占位符}}]


@dataclass
class RoundTrace:
    """单条规则在一轮里新增的事实（与旧版引擎输出格式兼容）。"""
    rule_name: str
    description: str
    added: Set[Tuple[str, str, Any]] = field(default_factory=set)


class RuleContext:
    """规则触发上下文：图 + 事实 + 动态属性 + 动作。"""

    def __init__(self, engine: "RuleEngine", spec: RuleSpec) -> None:
        self.engine = engine
        self.spec = spec
        self._new: List[Fact] = []

    # ---- 图 ----
    @property
    def store(self) -> GraphStore:
        return self.engine.store

    def nodes(self, type_name: str):
        return [n for n in self.store.nodes() if n.type == type_name]

    def get(self, id: str):
        return self.store.get_node(id)

    def out_links(self, id: str, type: Optional[str] = None):
        return self.store.out_neighbors(id, type)

    def in_links(self, id: str, type: Optional[str] = None):
        return self.store.in_neighbors(id, type)

    # ---- 事实 ----
    def known(self, s: str, p: str) -> Optional[Fact]:
        return self.engine.facts.get((s, p))

    def facts_of(self, s: str) -> List[Fact]:
        return [f for k, f in self.engine.facts.items() if k[0] == s]

    def assert_(self, s: str, p: str, v: Any, evidence: Optional[List[str]] = None) -> bool:
        """断言新事实（已存在则跳过）；证据进入证明链。"""
        return self.engine._assert(self.spec, s, p, v, evidence or [])

    # ---- 时序动态属性 ----
    def dynamic(self, entity_id: str, slot: str) -> Optional[float]:
        """读绑定物化的动态属性（无绑定/无数据 → None）。"""
        if self.engine.bindings is None:
            return None
        return self.engine.bindings.read(entity_id, slot)

    # ---- 动作（程序式绑定） ----
    def action(self, name: str, **params) -> Optional[Any]:
        return self.engine._trigger_action(name, params)

    # ---- 注记（时间线/日志输出钩子） ----
    def note(self, msg: str) -> None:
        self.engine.notes.append(msg)


class RuleEngine:
    def __init__(self, store: GraphStore,
                 bindings: Optional[BindingRegistry] = None,
                 actions: Optional[Any] = None) -> None:
        self.store = store
        self.bindings = bindings
        self.actions = actions            # ActionRegistry（可选）
        self.rules: List[RuleSpec] = []
        self.facts: Dict[FactKey, Fact] = {}
        self.trace: List[RoundTrace] = []
        self.action_results: List[Any] = []
        self.notes: List[str] = []
        self._round = 0
        self._mutated = False             # 本轮内动作改过图 → 再跑一轮

    # ---------------------------------------------------------------- 装配
    def add_rule(self, spec: RuleSpec) -> None:
        self.rules.append(spec)

    def add_rules(self, specs: List[RuleSpec]) -> None:
        for s in specs:
            self.add_rule(s)

    def seed(self, tuples: Set[Tuple[str, str, Any]]) -> None:
        for s, p, v in tuples:
            self.facts.setdefault((s, p), Fact(s, p, v, "seed", 0))

    # ---------------------------------------------------------------- 内核
    def _assert(self, spec: RuleSpec, s: str, p: str, v: Any,
                evidence: List[str]) -> bool:
        key = (s, p)
        if key in self.facts:
            return False
        self.facts[key] = Fact(s, p, v, spec.name, self._round, evidence)
        return True

    def _trigger_action(self, name: str, params: Dict[str, Any]) -> Optional[Any]:
        if self.actions is None:
            return None
        crud = getattr(self.actions.ctx, "crud", None)
        before = crud.version if crud else None
        result = self.actions.execute(name, **params)
        if result is not None:
            self.action_results.append(result)
            if crud is not None and crud.version != before:
                self.invalidate_derived()   # 图真的变了 → 派生事实作废重推
                self._mutated = True        # → 强制再迭代一轮
        return result

    def invalidate_derived(self) -> None:
        """图变更后失效所有派生事实（seed 事实保留）。"""
        self.facts = {k: f for k, f in self.facts.items() if f.source == "seed"}

    def run(self, max_rounds: int = 20) -> List[RoundTrace]:
        """正向链固定点：每轮按优先级序触发全部规则，直到无新事实且无图变更。"""
        ordered = sorted(self.rules, key=lambda r: (-r.priority, r.name))
        self.notes = []            # 每次 run 汇总一次（跨轮累积）
        self.action_results = []
        for _ in range(max_rounds):
            self._round += 1
            self._mutated = False
            round_added = 0
            for spec in ordered:
                before = len(self.facts)
                ctx = RuleContext(self, spec)
                spec.fire(ctx)
                newly = {key: f for key, f in self.facts.items()
                         if f.source == spec.name and f.round == self._round}
                if newly:
                    added = {f.as_tuple() for f in newly.values()}
                    self.trace.append(RoundTrace(spec.name, spec.description, added))
                    round_added += len(added)
                    # 声明式动作绑定（占位符 {s}/{p}/{v} 取自断言事实）
                    for binding in spec.actions:
                        for f in newly.values():
                            params = {
                                k: (str(v).format(s=f.s, p=f.p, v=f.v) if isinstance(v, str) else v)
                                for k, v in binding.get("params", {}).items()
                            }
                            self._trigger_action(binding["action"], params)
            if round_added == 0 and not self._mutated:
                break
        return self.trace

    # ---------------------------------------------------------------- 证明链
    def explain(self, s: str, p: str) -> str:
        """「为什么推出这个结论」：事实 ← 规则（第几轮）← 证据。"""
        f = self.facts.get((s, p))
        if f is None:
            return f"未推出 ({s}, {p})"
        lines = [f"({s} --{p}--> {f.v})  ← [{f.source}] 第 {f.round} 轮"]
        for ev in f.evidence:
            lines.append(f"    └─ {ev}")
        return "\n".join(lines)

    def fact_tuples(self) -> Set[Tuple[str, str, Any]]:
        return {f.as_tuple() for f in self.facts.values()}
