# -*- coding: utf-8 -*-
"""仿真引擎：装配 本体图 + 时序库 + 场景，驱动仿真时钟。

写路径统一走 write()（Gate A：合并后 SHACL 校验，拒绝则不进图）——
仿真里的每一次写回都与生产写入路径同构。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from eo.crud import OntologyCRUD, ValidationError as GateAError
from eo.jsonld import export_jsonld, graph_to_entities
from eo.rules import (
    check_reachability, forward_chain, DOMAIN_RULES,
    intercept_action, propagate_fault_event, root_cause,
)
from eo.timeseries import SqliteTelemetryStore

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

        # ---- Gate A：世界数据入库前全量校验（唯一写路径：eo.crud.OntologyCRUD） ----
        with open(data_path, encoding="utf-8") as f:
            entities = json.load(f)
        self.crud = OntologyCRUD()
        try:
            self.crud.load(entities)
        except GateAError as e:
            raise ValueError(f"Gate A：世界数据未通过 SHACL 校验\n{e.report}") from e
        self.facts, _ = forward_chain(self.store, DOMAIN_RULES)

        self.telemetry = SqliteTelemetryStore(os.path.join(outputs, "telemetry.db"))
        self.timeline = Timeline(outputs)
        self.runtime = RobotRuntime(self, seed)
        self.dispatcher = TaskDispatcher(self)
        self.injector = FaultInjector(self)
        self._log_seq = 0

        self.timeline.event(0, "boot", f"世界就绪：{len(entities)} 实体过 Gate A，"
                                       f"规则引擎推出 {len(self.facts)} 条事实")

    # ---------------------------------------------------------------- 写路径
    @property
    def store(self):
        """本体图（由 CRUD 层持有，重建后引用不变）。"""
        return self.crud.store

    def write(self, updates: List[Dict[str, Any]], t: int) -> bool:
        """Gate A 写回（委托 OntologyCRUD.apply：浅合并 → 全量校验 → 原子提交）。"""
        try:
            self.crud.apply(updates)
        except GateAError as e:
            first = e.report.violations[0]
            self.timeline.event(t, "gate-a",
                                f"✗ 写回被拒绝：{first.focus_node} {first.message}")
            return False
        self.facts, _ = forward_chain(self.store, DOMAIN_RULES, set())  # 事实集失效重算
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
        """注入故障（按 FaultMode 模式库）。"""
        return self.injector.inject(mode_id, t)

    def reachability(self, task_id: str):
        return check_reachability(self.store, task_id)

    def intercept(self, task_id: str):
        return intercept_action(self.store, task_id)

    def propagate(self, event_id: str):
        return propagate_fault_event(self.store, event_id)

    def root_cause(self, task_id: str):
        return root_cause(self.store, task_id)

    def iso(self, t: int) -> str:
        return iso(t)
