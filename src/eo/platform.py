# -*- coding: utf-8 -*-
"""本体 ↔ robot-dispatch 平台桥接（docs/06）。

把本体引擎的数据映射成平台已有契约的格式，平台零改动即可接入：

- build_platform_telemetry：本体 → 平台 TelemetryPayload（flat 字段 + ti5 细粒度透传）
- build_platform_robot    ：本体 Robot → 平台 Robot 模型的本体可知字段

平台契约来源（已查实）：
  robot-dispatch-server/internal/handler/telemetry.go  TelemetryPayload（23 字段，全可选）
  robot-dispatch-server/internal/model/national.go     Robot 模型

本体不知道的平台业务字段（project_id/city/owner/form/scene…）一律留空，
由平台侧台账补齐——本体只负责「具身」这一半，不越界造业务字段。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .graph.base import GraphStore
from .timeseries.base import TelemetryStore
from .timeseries.binding import BindingRegistry

ONTOLOGY_VERSION = "1.1.0"


def _telemetry_payload_fields() -> Dict[str, Any]:
    """平台 TelemetryPayload 的字段骨架（字段全可选）。"""
    return {
        "robot_id": None, "battery": None, "status": None, "temp": None,
        "signal": None, "area": None, "task": None, "ti5": None,
        "charging": None, "ip": None, "wifi_ssid": None, "app_version": None,
        "sn": None, "map_name": None, "located": None,
        "pos_x": None, "pos_y": None, "pos_theta": None,
        "odometer": None, "today_km": None, "today_min": None,
        "cur_speed": None, "estop": None,
    }


def _pack_ti5_metrics(telemetry: TelemetryStore, bindings: BindingRegistry) -> Dict[str, Any]:
    """把本体的细粒度测点（(entity, metric) → 最新值）打包成平台 ti5 字段的 JSON。"""
    metrics: Dict[str, Dict[str, float]] = {}
    for b in bindings.bindings:
        row = telemetry.last(b.entity_ref, b.metric_code)
        if row is not None:
            metrics.setdefault(b.entity_ref, {})[b.metric_code] = row.value
    return {"ontology_version": ONTOLOGY_VERSION, "metrics": metrics}


def build_platform_telemetry(store: GraphStore, telemetry: TelemetryStore,
                             bindings: BindingRegistry, robot_id: str) -> Optional[Dict[str, Any]]:
    """本体 → 平台 TelemetryPayload（对齐 telemetry.go）。

    - flat 字段来自本体机器人台账 + 动态属性（battery 经时序绑定物化）
    - ti5 字段打包本体细粒度测点（平台原样透传，后续可解包）
    """
    robot = store.get_node(robot_id)
    if robot is None or robot.type != "Robot":
        return None

    payload = _telemetry_payload_fields()
    battery = bindings.read(robot_id, "current_battery")
    payload.update({
        "robot_id": robot_id,
        "battery": int(battery) if battery is not None else None,
        "status": robot.get("status"),
        "sn": robot.get("serial"),
        "app_version": robot.get("firmware_version"),
        "ti5": json.dumps(_pack_ti5_metrics(telemetry, bindings), ensure_ascii=False),
    })
    return payload


def build_platform_robot(store: GraphStore, robot_id: str) -> Optional[Dict[str, Any]]:
    """本体 Robot → 平台 Robot 模型的本体可知字段（其余留空由平台补齐）。"""
    robot = store.get_node(robot_id)
    if robot is None or robot.type != "Robot":
        return None
    return {
        "id": robot_id,
        "name": robot.get("label"),
        "model": robot.get("model"),
        "status": robot.get("status"),
        "sn": robot.get("serial"),
        "fw": robot.get("firmware_version"),
        # 平台业务字段（project_id/city/owner/form/scene…）本体不管，留空
    }
