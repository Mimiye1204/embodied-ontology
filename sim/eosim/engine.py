# -*- coding: utf-8 -*-
"""仿真引擎：本体 CRUD + 时序绑定 + 规则框架 + Action 注册表 + 场景时钟。

写路径统一走 eo.crud.OntologyCRUD（Gate A）；
调度/故障/写回统一走 eo.actions.ActionRegistry（受控动作 + 自动审计）；
推理统一走 eo.rules.framework.RuleEngine（证明链 + 动态属性 + 动作绑定）。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from eo.actions import build_registry
from eo.crud import OntologyCRUD, ValidationError as GateAError
from eo.io import load_entities_file
from eo.jsonld import export_jsonld
from eo.rules import DOMAIN_RULES, check_reachability, intercept_action
from eo.rules.framework import RuleEngine
from eo.timeseries import SqliteTelemetryStore
from eo.timeseries.binding import BindingRegistry

from .clock import iso
from .dispatch import TaskDispatcher
from .faults import FaultInjector
from .runtime import RobotRuntime
from .timeline import Timeline


class SimulationEngine:
    def __init__(self, scenario, data_path: str, outputs: str = "sim/outputs",
                 seed: int = 0) -> None:
        import random
        self.random = random.Random(seed)
        self.scenario = scenario
        self.outputs = outputs
        self.t = 0
        import shutil
        shutil.rmtree(outputs, ignore_errors=True)  # 每次运行清空产物
        os.makedirs(outputs, exist_ok=True)

        # ---- Gate A：世界数据入库（唯一写路径 OntologyCRUD） ----
        # 支持 .json（原始实体清单）与 .jsonld（JSON-LD 文档，自动 round-trip）
        entities = load_entities_file(data_path)
        self.crud = OntologyCRUD()
        try:
            self.crud.load(entities)
        except GateAError as e:
            raise ValueError(f"Gate A：世界数据未通过 SHACL 校验\n{e.report}") from e

        self.telemetry = SqliteTelemetryStore(os.path.join(outputs, "telemetry.db"))
        self.timeline = Timeline(outputs)

        # ---- 时序属性绑定（测点注册表 binds_to 声明） ----
        self.bindings = BindingRegistry(self.store, self.telemetry)
        binding_errors = self.bindings.validate_bindings()
        if binding_errors:
            raise ValueError("时序绑定校验失败：\n" + "\n".join(binding_errors))

        # ---- Action 注册表（受控写操作 + 自动审计） ----
        self.actions = build_registry(
            self.crud, now=lambda: iso(self.t),
            sink=lambda source, msg: self.timeline.event(self.t, source, msg))

        # ---- 规则引擎框架（证明链/动态属性/动作绑定） ----
        self.rules = RuleEngine(self.store, bindings=self.bindings, actions=self.actions)
        self.rules.add_rules(DOMAIN_RULES)

        self.runtime = RobotRuntime(self, seed)
        self.dispatcher = TaskDispatcher(self)
        self.injector = FaultInjector(self)
        self._log_seq = 0

        self.rules.run()
        self.timeline.event(0, "boot", f"世界就绪：{len(entities)} 实体过 Gate A，"
                                       f"规则引擎推出 {len(self.rules.facts)} 条事实，"
                                       f"时序绑定 {len(self.bindings.bindings)} 个")

    # ---------------------------------------------------------------- 访问
    @property
    def store(self):
        """本体图（由 CRUD 层持有，重建后引用不变）。"""
        return self.crud.store

    @property
    def facts(self):
        return self.rules.fact_tuples()

    # ---------------------------------------------------------------- 写路径
    def write(self, updates: List[Dict[str, Any]], t: int) -> bool:
        """Gate A 写回（委托 OntologyCRUD.apply；图变更后失效派生事实并重跑规则）。"""
        before = self.crud.version
        try:
            self.crud.apply(updates)
        except GateAError as e:
            first = e.report.violations[0]
            self.timeline.event(t, "gate-a",
                                f"✗ 写回被拒绝：{first.focus_node} {first.message}")
            return False
        if self.crud.version != before:
            self.rules.invalidate_derived()
        self.rules.run()
        return True

    def log_action(self, t: int, action_type: str, target: str, result: str,
                   detail: Optional[str] = None) -> None:
        """写回审计（ActionLog，ADR-3）：所有写操作必经。"""
        self._log_seq += 1
        entry = {
            "id": f"eo:log/sim-{self._log_seq:04d}",
            "type": "ActionLog",
            "label": f"{action_type} → {target}",
            "action_type": action_type,
            "actor": "simulation",
            "target": target,
            "detail": detail or "",
            "result": result,
            "occurred_at": iso(t),
            "created_at": iso(t),
        }
        self.write([entry], t)

    # ---------------------------------------------------------------- 主循环
    def run(self, steps: Optional[int] = None) -> None:
        duration = steps if steps is not None else self.scenario.duration
        self.scenario.setup(self)
        for t in range(1, duration + 1):
            self.t = t
            self.runtime.tick(t)
            self.scenario.tick(self, t)
            self.dispatcher.advance(t)

        # ---- 收尾：Gate C 校验 + JSON-LD 快照 ----
        report = self.crud.validate()
        self.timeline.event(duration, "gate-c",
                            f"终态 {len(self.crud.entities)} 实体校验："
                            f"{'通过 ✓' if report.conforms else '失败 ✗'}")
        export_jsonld(self.store, os.path.join(self.outputs, "fleet-final.jsonld"))
        self.timeline.event(duration, "finish",
                            f"快照 fleet-final.jsonld / telemetry.db 已写入 {self.outputs}")
        self.telemetry.close()
        self.timeline.close()

    # ---------------------------------------------------------------- 便捷
    def inject_fault(self, mode_id: str, t: int):
        return self.injector.inject(mode_id, t)

    def reachability(self, task_id: str):
        return check_reachability(self.store, task_id)

    def intercept(self, task_id: str):
        return intercept_action(self.store, task_id)

    def root_cause(self, task_id: str):
        from eo.rules.faults import root_cause
        return root_cause(self.store, task_id)
