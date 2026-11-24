# -*- coding: utf-8 -*-
"""Action 绑定模型（docs/04 §3 设计落地）：受控写操作注册表。

对齐 Palantir ActionType 思想 + ADR-3 审计：
- Action 定义 = 名称/描述/可作用的目标 ObjectType/参数规约/处理器
- 执行管线：参数校验 → 目标绑定校验（存在 + 类型 ∈ targets）
  → 处理器（内部经 OntologyCRUD 唯一写路径，Gate A/B 由处理器调用）
  → 自动 ActionLog 审计（谁、对谁、做了什么、结果）→ ActionResult
- 规则引擎通过 RuleSpec.actions 声明式绑定动作（断言新事实 → 自动写回）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .crud import CRUDError, OntologyCRUD, ValidationError
from .rules.faults import propagate_fault_event
from .rules.intercept import intercept_action
from .rules.reachability import check_reachability, robot_of_part


@dataclass
class ActionResult:
    ok: bool
    action: str
    target: Optional[str] = None
    messages: List[str] = field(default_factory=list)
    audit_log_id: Optional[str] = None
    patches: List[Dict[str, Any]] = field(default_factory=list)

    def __str__(self) -> str:
        head = "✓" if self.ok else "✗"
        return f"{head} {self.action}" + (f" → {self.target}" if self.target else "")


class ActionContext:
    """动作执行上下文：CRUD（唯一写路径）+ 规则引擎 + 时钟 + 事件汇。"""

    def __init__(self, crud: OntologyCRUD,
                 rules: Optional[Any] = None,
                 now: Optional[Callable[[], str]] = None,
                 sink: Optional[Callable[[str, str], None]] = None) -> None:
        self.crud = crud
        self.rules = rules
        self.now = now or (lambda: datetime.now(timezone.utc).isoformat())
        self.sink = sink or (lambda source, msg: None)
        self._seq_cache: Dict[str, int] = {}

    def _next_seq(self, prefix: str) -> int:
        """从库中已有 id 续号（跨进程防冲突）。"""
        if prefix not in self._seq_cache:
            mx = 0
            for eid in self.crud.entities:
                if eid.startswith(prefix):
                    try:
                        mx = max(mx, int(eid[len(prefix):]))
                    except ValueError:
                        pass
            self._seq_cache[prefix] = mx
        self._seq_cache[prefix] += 1
        return self._seq_cache[prefix]

    def audit(self, action_name: str, actor: str, target: Optional[str],
              params: Dict[str, Any], result: str) -> Optional[str]:
        """自动审计：ActionLog 实体（经 Gate A 落库）。返回审计 id。"""
        seq = self._next_seq("eo:log/action-")
        entry = {
            "id": f"eo:log/action-{seq:04d}",
            "type": "ActionLog",
            "label": f"{action_name} → {target or '-'}",
            "action_type": action_name,
            "actor": actor,
            "target": target,
            "detail": json.dumps(params, ensure_ascii=False)[:500],
            "result": result,
            "occurred_at": self.now(),
            "created_at": self.now(),
        }
        try:
            self.crud.create(entry)
            return entry["id"]
        except (CRUDError, ValidationError):
            return None


class Action:
    """受控写操作（ActionType 实例）。"""

    def __init__(self, name: str, description: str, handler: Callable,
                 params: Optional[Dict[str, str]] = None,
                 targets: Optional[List[str]] = None,
                 target_param: Optional[str] = None) -> None:
        self.name = name
        self.description = description
        self.handler = handler
        self.params = params or {}        # 参数规约：名称 → 类型名
        self.targets = targets or []      # 可作用的 ObjectType
        self.target_param = target_param  # 哪个参数是目标实体 id

    def execute(self, ctx: ActionContext, actor: str = "system",
                **params: Any) -> ActionResult:
        # ---- 1. 参数校验 ----
        missing = [k for k in self.params if k not in params]
        if missing:
            result = ActionResult(False, self.name,
                                  messages=[f"缺少参数：{missing}"])
            ctx.audit(self.name, actor, None, params, "rejected")
            return result

        # ---- 2. 目标绑定校验（存在 + 类型 ∈ targets） ----
        target: Optional[str] = None
        if self.target_param:
            target = params.get(self.target_param)
            ent = ctx.crud.get(target) if target else None
            if target and ent is None:
                result = ActionResult(False, self.name, target=target,
                                      messages=[f"目标 {target} 不存在"])
                ctx.audit(self.name, actor, target, params, "rejected")
                return result
            if ent is not None and self.targets and ent["type"] not in self.targets:
                result = ActionResult(False, self.name, target=target,
                                      messages=[f"目标 {target} 类型 {ent['type']} "
                                                f"不在允许范围 {self.targets}"])
                ctx.audit(self.name, actor, target, params, "rejected")
                return result

        # ---- 3. 处理器（写操作经 CRUD → Gate A/B） ----
        try:
            result = self.handler(ctx, **params)
        except ValidationError as e:
            result = ActionResult(False, self.name, target=target,
                                  messages=[f"Gate A 拒绝：{e.report.violations[0].message}"])
        except CRUDError as e:
            result = ActionResult(False, self.name, target=target, messages=[str(e)])

        # ---- 4. 自动审计 ----
        outcome = "ok" if result.ok else "failed"
        result.audit_log_id = ctx.audit(self.name, actor, target, params, outcome)
        if ctx.sink:
            ctx.sink("action", str(result))
        return result


class ActionRegistry:
    """ActionType 注册表：register / execute / list。"""

    def __init__(self, ctx: ActionContext) -> None:
        self.ctx = ctx
        self.actions: Dict[str, Action] = {}

    def register(self, action: Action) -> None:
        self.actions[action.name] = action

    def get(self, name: str) -> Optional[Action]:
        return self.actions.get(name)

    def execute(self, name: str, actor: str = "system", **params: Any) -> Optional[ActionResult]:
        action = self.actions.get(name)
        if action is None:
            return None
        return action.execute(self.ctx, actor, **params)

    def list(self) -> List[Dict[str, Any]]:
        return [{"name": a.name, "description": a.description,
                 "params": a.params, "targets": a.targets}
                for a in self.actions.values()]


# ================================================================ 内建动作
def _dispatch_task(ctx: ActionContext, **p: Any) -> ActionResult:
    """task.dispatch：Gate B（可达性 + 拦截）→ 状态迁移 + verdict 写回。"""
    task_id = p["task_id"]
    r = check_reachability(ctx.crud.store, task_id)
    patches: List[Dict[str, Any]] = [{"id": task_id, "verdict": r.verdict}]
    if r.verdict == "infeasible":
        patches.append({"id": task_id, "status": "failed"})
        msgs = [f"✗ 不可达：{'；'.join(r.problems)}"]
    else:
        hits = intercept_action(ctx.crud.store, task_id)
        if hits:
            patches.append({"id": task_id, "status": "intercepted"})
            msgs = [f"⛔ 拦截 {len(hits)} 项："] + \
                   [f"    [{h.kind}] {h.rewrite}" for h in hits]
        else:
            patches.append({"id": task_id, "status": "executing"})
            msgs = ["✓ 放行 → executing"]
    ctx.crud.apply(patches)
    return ActionResult(True, "task.dispatch", target=task_id,
                        messages=msgs, patches=patches)


def _reassign_task(ctx: ActionContext, **p: Any) -> ActionResult:
    """task.reassign：改派机器人（目标绑定校验在 Action.execute 完成）。"""
    task_id, robot_id = p["task_id"], p["robot_id"]
    robot = ctx.crud.get(robot_id)
    if robot is None or robot["type"] != "Robot":
        return ActionResult(False, "task.reassign", target=task_id,
                            messages=[f"改派目标 {robot_id} 不存在或不是 Robot"])
    ctx.crud.apply([
        {"id": task_id, "assigned_to": robot_id, "status": "pending"},
    ])
    return ActionResult(True, "task.reassign", target=task_id,
                        messages=[f"→ 改派至 {robot_id}"],
                        patches=[{"id": task_id, "assigned_to": robot_id}])


def _cancel_task(ctx: ActionContext, **p: Any) -> ActionResult:
    """task.cancel：取消任务（终态保护）。"""
    task_id = p["task_id"]
    task = ctx.crud.get(task_id)
    if task.get("status") in ("succeeded", "failed", "canceled"):
        return ActionResult(False, "task.cancel", target=task_id,
                            messages=[f"终态任务不可取消（{task.get('status')}）"])
    ctx.crud.apply([{"id": task_id, "status": "canceled"}])
    return ActionResult(True, "task.cancel", target=task_id,
                        messages=["✓ 已取消"], patches=[{"id": task_id, "status": "canceled"}])


def _report_fault(ctx: ActionContext, **p: Any) -> ActionResult:
    """fault.report：按故障模式库上报（建事件 + 部件置 fault + 传播）。"""
    mode_id = p["mode_id"]
    mode = ctx.crud.get(mode_id)
    parts = [x for x in mode.get("affects_bodypart", [])] if mode else []
    if not parts:
        return ActionResult(False, "fault.report", target=mode_id,
                            messages=[f"模式 {mode_id} 不存在或无关联部件"])
    reporter = robot_of_part(ctx.crud.store, parts[0])
    # 事件 id 从库中续号（跨进程防冲突）
    seq = ctx._next_seq("eo:event/action-")
    event_id = f"eo:event/action-{seq:04d}"
    entry = {
        "id": event_id, "type": "FaultEvent",
        "label": f"动作上报：{mode.get('label')}",
        "of_mode": mode_id,
        "affects_bodypart": parts[0],
        "severity": mode.get("default_severity") or "critical",
        "status": "active",
        "detected_at": ctx.now(),
        "created_at": ctx.now(),
    }
    if reporter:
        entry["reported_by"] = reporter
    ctx.crud.apply([entry] + [{"id": x, "health": "fault"} for x in parts])
    impact = propagate_fault_event(ctx.crud.store, event_id)
    return ActionResult(True, "fault.report", target=event_id,
                        messages=[
                            f"⚠ {event_id} 注入（模式 {mode_id}）",
                            f"  受影响部件 {impact.faulty_parts}",
                            f"  → 能力失效 {impact.lost_capabilities}",
                            f"  → 受影响任务 {impact.affected_tasks}",
                        ],
                        patches=[entry])


def _writeback(ctx: ActionContext, **p: Any) -> ActionResult:
    """knowledge.writeback：归纳写回（通用受控更新，Gate A）。"""
    entity_id = p["entity_id"]
    patch = p.get("patch") or {}
    ctx.crud.update(entity_id, dict(patch))
    return ActionResult(True, "knowledge.writeback", target=entity_id,
                        messages=[f"✓ 写回 {entity_id}: {patch}"],
                        patches=[{"id": entity_id, **patch}])


def _create_entity(ctx: ActionContext, **p: Any) -> ActionResult:
    """entity.create：受控新建实体（Gate A）。"""
    entity = dict(p.get("entity") or {})
    ctx.crud.create(entity)
    return ActionResult(True, "entity.create", target=entity.get("id"),
                        messages=[f"✓ 已创建 {entity.get('id')}"],
                        patches=[entity])


def build_registry(crud: OntologyCRUD, rules: Optional[Any] = None,
                   now: Optional[Callable[[], str]] = None,
                   sink: Optional[Callable[[str, str], None]] = None) -> ActionRegistry:
    """装配内建动作注册表（扩展：reg.register(Action(...))）。"""
    ctx = ActionContext(crud, rules=rules, now=now, sink=sink)
    reg = ActionRegistry(ctx)
    reg.register(Action(
        "task.dispatch", "下发任务：可达性 + 拦截检查 → 状态迁移（Gate B）",
        _dispatch_task, params={"task_id": "str"},
        targets=["Task"], target_param="task_id"))
    reg.register(Action(
        "task.reassign", "改派任务到机器人",
        _reassign_task, params={"task_id": "str", "robot_id": "str"},
        targets=["Task"], target_param="task_id"))
    reg.register(Action(
        "task.cancel", "取消任务（终态保护）",
        _cancel_task, params={"task_id": "str"},
        targets=["Task"], target_param="task_id"))
    reg.register(Action(
        "fault.report", "按故障模式库上报故障：建事件 + 传播",
        _report_fault, params={"mode_id": "str"},
        targets=["FaultMode"], target_param="mode_id"))
    reg.register(Action(
        "knowledge.writeback", "归纳写回：受控更新实体属性（Gate A）",
        _writeback, params={"entity_id": "str", "patch": "dict"}))
    reg.register(Action(
        "entity.create", "受控新建实体（Gate A）",
        _create_entity, params={"entity": "dict"}))
    return reg
