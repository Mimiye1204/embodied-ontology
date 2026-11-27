# -*- coding: utf-8 -*-
"""硬件方案 → 本体 Object / Link / 绑定 Action 自动生成（docs/01 §5 方法C）。

输入：硬件蓝图（声明式 YAML/JSON，见 hardware/ti5.yaml）
输出三件套：
  1. Object —— Robot / BodyPart（部件树）/ Capability / Constraint 实体
  2. Link   —— part_of（树）/ provides_capability / has_part / constrains
  3. Action —— 蓝图声明的动作绑定到内建 handler，产出 ActionRegistry

生成的实体走 Gate A（SHACL）校验，失败拒绝（ValidationError）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .actions import Action, ActionContext, ActionRegistry, HANDLER_BY_NAME
from .crud import OntologyCRUD

DEFAULT_CREATED_AT = "2026-11-27T08:00:00+08:00"


def load_blueprint(path: str) -> Dict[str, Any]:
    """加载硬件蓝图（YAML 或 JSON）。"""
    with open(path, encoding="utf-8") as f:
        if path.endswith(".json"):
            import json
            return json.load(f)
        import yaml
        return yaml.safe_load(f)


def generate_entities(bp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """蓝图 → 本体实体清单（Link 槽内联为紧凑 IRI 引用）。"""
    robot = bp["robot"]
    robot_id = robot["id"]
    created_at = robot.get("created_at", DEFAULT_CREATED_AT)

    declared_caps = {c["code"] for c in bp.get("capabilities", [])}
    cap_ids = {c: f"eo:cap/{c}" for c in declared_caps}
    entities: List[Dict[str, Any]] = []

    # ---- Object: 能力注册表 ----
    for c in bp.get("capabilities", []):
        entities.append({
            "id": cap_ids[c["code"]], "type": "Capability",
            "label": c["label"], "code": c["code"], "created_at": created_at,
        })

    # ---- Object + Link: 部件树（children → part_of；capabilities → provides） ----
    def walk(part: Dict[str, Any], parent_path: str, parent_id: Optional[str]) -> str:
        pid = f"{parent_path}/{part['id']}" if parent_path else part["id"]
        part_eid = f"eo:part/{robot_id}/{pid}"
        ent: Dict[str, Any] = {
            "id": part_eid, "type": "BodyPart",
            "label": part.get("label", part["id"]),
            "health": "ok", "created_at": created_at,
        }
        for slot in ("dof", "load_capacity_kg", "torque_limit_nm", "grip_force_n"):
            if slot in part:
                ent[slot] = part[slot]
        if parent_id:                       # Link: part_of
            ent["part_of"] = parent_id
        caps = part.get("capabilities", [])
        for code in caps:
            if code not in declared_caps:
                raise ValueError(f"部件 {part['id']} 引用了未声明的能力 {code}（capabilities 清单缺）")
        if caps:                            # Link: provides_capability
            ent["provides_capability"] = [cap_ids[c] for c in caps]
        entities.append(ent)

        # ---- Object + Link: 约束（constrains → 本部件） ----
        for con in part.get("constraints", []):
            c_ent: Dict[str, Any] = {
                "id": f"eo:constraint/{con['code']}", "type": "Constraint",
                "label": con.get("label", con["code"]),
                "constraint_type": con["type"],
                "constrains": part_eid,      # Link: constrains
                "created_at": created_at,
            }
            # 可选字段只写存在的（缺 expression 会触发 Gate A 的 required 校验）
            for src, dst in (("expression", "expression"), ("threshold", "threshold"),
                             ("unit", "unit"), ("rewrite", "suggested_rewrite")):
                if src in con:
                    c_ent[dst] = con[src]
            entities.append(c_ent)

        for child in part.get("children", []):
            walk(child, pid, part_eid)
        return part_eid

    top_part_ids = [walk(p, "", None) for p in bp.get("parts", [])]

    # ---- Object + Link: Robot（has_part → 部件树根） ----
    entities.append({
        "id": f"eo:robot/{robot_id}", "type": "Robot",
        "label": robot.get("label", robot_id),
        "serial": robot.get("serial", ""),
        "model": robot.get("model", ""),
        "status": robot.get("status", "online"),
        "has_part": top_part_ids,            # Link: has_part
        "created_at": created_at,
    })
    return entities


def generate_registry(bp: Dict[str, Any], crud: OntologyCRUD,
                      now=None, sink=None) -> ActionRegistry:
    """蓝图声明的动作 → 绑定到内建 handler 的 ActionRegistry。"""
    ctx = ActionContext(crud, now=now, sink=sink)
    reg = ActionRegistry(ctx)
    for a in bp.get("actions", []):
        handler = HANDLER_BY_NAME.get(a.get("handler", a["name"]))
        if handler is None:
            raise ValueError(f"未知动作 handler: {a.get('handler')}（可用：{sorted(HANDLER_BY_NAME)}）")
        reg.register(Action(
            name=a["name"], description=a.get("description", ""),
            handler=handler,
            params=a.get("params", {}),
            targets=a.get("targets", []),
            target_param=a.get("target_param"),
        ))
    return reg


def build_from_blueprint(bp: Dict[str, Any],
                         now=None, sink=None) -> Tuple[OntologyCRUD, ActionRegistry]:
    """完整流水线：蓝图 → 实体（Gate A 校验）→ 建图 → 绑定动作注册表。"""
    entities = generate_entities(bp)
    crud = OntologyCRUD()
    crud.load(entities)   # Gate A：非法蓝图在此抛 ValidationError
    registry = generate_registry(bp, crud, now=now, sink=sink)
    return crud, registry
