# -*- coding: utf-8 -*-
"""故障注入器：按 FaultMode 模式库触发故障事件（Gate A 写回 + 传播 + 审计）。"""
from __future__ import annotations

from typing import Optional

from .clock import iso


class FaultInjector:
    def __init__(self, engine) -> None:
        self.engine = engine
        self._seq = 0

    def robot_of_part(self, part_id: str) -> Optional[str]:
        """部件 → 所属机器人（has_part 根 + part_of 链）。"""
        env = self.engine
        for robot in env.store.nodes():
            if robot.type != "Robot":
                continue
            roots = {p.id for p in env.store.out_neighbors(robot.id, "has_part")}
            cur: Optional[str] = part_id
            seen = set()
            while cur and cur not in seen:
                seen.add(cur)
                if cur in roots:
                    return robot.id
                parents = env.store.out_neighbors(cur, "part_of")
                cur = parents[0].id if parents else None
        return None

    def inject(self, mode_id: str, t: int) -> Optional[dict]:
        """按模式库注入故障：建 FaultEvent（Gate A 校验）→ 部件置 fault → 传播。"""
        env = self.engine
        mode = env.store.get_node(mode_id)
        if mode is None or mode.type != "FaultMode":
            env.timeline.event(t, "fault", f"✗ 模式 {mode_id} 不存在")
            return None

        parts = [p.id for p in env.store.out_neighbors(mode_id, "affects_bodypart")]
        if not parts:
            env.timeline.event(t, "fault", f"✗ 模式 {mode_id} 未关联任何部件")
            return None

        self._seq += 1
        event_id = f"eo:event/sim-fault-{self._seq:03d}"
        reporter = self.robot_of_part(parts[0])
        event = {
            "id": event_id, "type": "FaultEvent",
            "label": f"仿真注入：{mode.get('label')}",
            "of_mode": mode_id,
            "affects_bodypart": parts[0],
            "severity": mode.get("default_severity") or "critical",
            "status": "active",
            "detected_at": iso(t),
            "created_at": iso(t),
        }
        if reporter:
            event["reported_by"] = reporter

        if not env.write([event], t):
            return None
        env.log_action(t, "fault.inject", mode_id, "ok", detail=event_id)

        # 部件健康状态写回（Gate A 同路径，补丁浅合并保留其余槽）
        env.write([{"id": p, "type": "BodyPart", "health": "fault"} for p in parts], t)

        impact = env.propagate(event_id)
        env.timeline.event(t, "fault", f"⚠ {event_id} 注入（模式 {mode_id}）")
        env.timeline.event(t, "fault", f"  受影响部件 {impact.faulty_parts}")
        env.timeline.event(t, "fault", f"  → 能力失效 {impact.lost_capabilities}")
        env.timeline.event(t, "fault", f"  → 受影响任务 {impact.affected_tasks}")
        return {"event": event_id, "impact": impact}
