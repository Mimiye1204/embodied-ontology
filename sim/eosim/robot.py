# -*- coding: utf-8 -*-
"""机器人运行时实例：本体导入后自动实例化。

RobotInstance 是「本体 Robot 实体」的运行时把手：
  - 身份绑定：id / serial / model / status（来自本体实体）
  - 结构：部件树（part_of_robot）、能力（provides_capability 聚合）
  - 动态状态：健康聚合（部件 health）、电量（时序绑定物化）、遥测快照

instantiate_robots(engine)：扫描本体图里全部 Robot 实体，一台一个实例。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from eo.rules.reachability import part_of_robot


class RobotInstance:
    def __init__(self, engine, robot_node) -> None:
        self.engine = engine
        self.id: str = robot_node.id
        self.serial: str = robot_node.get("serial", "")
        self.model: str = robot_node.get("model", "")
        self.status: str = robot_node.get("status", "online")

    @property
    def store(self):
        return self.engine.store

    # ---------------------------------------------------------------- 结构
    def parts(self) -> List:
        """该机器人的全部部件（BodyPart 节点，按 id 排序）。"""
        return sorted(
            [p for p in self.store.nodes()
             if p.type == "BodyPart" and part_of_robot(self.store, p.id, self.id)],
            key=lambda n: n.id,
        )

    def capabilities(self) -> List[str]:
        """该机器人部件提供的全部能力 code。"""
        caps = set()
        for p in self.parts():
            for c in self.store.out_neighbors(p.id, "provides_capability"):
                caps.add(c.get("code", ""))
        return sorted(caps)

    # ---------------------------------------------------------------- 动态状态
    def health(self) -> str:
        """聚合健康：任一部件 fault → fault；否则任一 degraded → degraded；否则 ok。"""
        states = {p.get("health", "ok") for p in self.parts()}
        if "fault" in states:
            return "fault"
        if "degraded" in states:
            return "degraded"
        return "ok"

    def battery(self) -> Optional[float]:
        """当前电量（时序绑定物化的动态属性）。"""
        if self.engine.bindings is None:
            return None
        return self.engine.bindings.read(self.id, "current_battery")

    def snapshot(self) -> dict:
        """当前状态快照：身份 + 健康 + 电量 + 能力 + 部件。"""
        return {
            "id": self.id,
            "serial": self.serial,
            "model": self.model,
            "status": self.status,
            "health": self.health(),
            "battery": self.battery(),
            "capabilities": self.capabilities(),
            "parts": [p.id for p in self.parts()],
        }

    def __repr__(self) -> str:
        return (f"RobotInstance({self.id}, {self.model}, health={self.health()}, "
                f"battery={self.battery()}, {len(self.capabilities())} 能力)")


def instantiate_robots(engine) -> Dict[str, RobotInstance]:
    """扫描本体图，自动实例化所有机器人（一台一个 RobotInstance）。"""
    return {n.id: RobotInstance(engine, n)
            for n in engine.store.nodes() if n.type == "Robot"}
