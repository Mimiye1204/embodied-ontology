# -*- coding: utf-8 -*-
"""测试运行器：零 pytest 依赖，plain assert。

运行：.venv/Scripts/python.exe tests/run_tests.py
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from eo.graph import MemoryStore
from eo.graph.loader import load_entities, load_json_file
from eo.jsonld import export_jsonld, from_jsonld_document
from eo.crud import CRUDError, OntologyCRUD, ValidationError as CRUDValidationError
from eo.actions import build_registry
from eo.rules import (
    DOMAIN_RULES, check_reachability, forward_chain,
    intercept_action, propagate_fault, propagate_fault_event, root_cause,
)
from eo.rules.framework import RuleEngine, RuleContext, RuleSpec
from eo.shacl import validate_entities
from eo.timeseries import SqliteTelemetryStore
from eo.timeseries.binding import BindingRegistry

DATA = os.path.join(os.path.dirname(__file__), "..", "examples", "fleet.json")


def _load():
    store = load_json_file(MemoryStore(), DATA)
    with open(DATA, encoding="utf-8") as f:
        entities = json.load(f)
    return store, entities


def _bad(mutate):
    entities = copy.deepcopy(json.load(open(DATA, encoding="utf-8")))
    mutate(entities)
    return entities


# ---------------------------------------------------------------- SHACL L0/L1
def test_shacl_valid():
    _, entities = _load()
    ok, report = validate_entities(entities)
    assert ok, report


def test_l0_rejects_bad_values():
    def m(es):
        for e in es:
            if e["id"] == "eo:object/cup":
                e["weight_kg"] = -1.0
                e["surface"] = "wet"
    ok, _ = validate_entities(_bad(m))
    assert not ok, "负重量与枚举越界应被 L0 拦截"


def test_l0_rejects_unknown_property():
    def m(es):
        for e in es:
            if e["id"] == "eo:object/cup":
                e["wieght_kg"] = 0.3
    ok, _ = validate_entities(_bad(m))
    assert not ok, "closed 形状应拦截拼写错误的属性"


def test_l1_rejects_dangling_link():
    def m(es):
        for e in es:
            if e["id"] == "eo:task/carry-cup":
                e["requires_capability"] = ["eo:cap/nonexistent"]
    ok, _ = validate_entities(_bad(m))
    assert not ok, "悬空引用应被 L1 引用完整性拦截"


def test_l1_rejects_duplicate_unique_key():
    def m(es):
        for e in es:
            if e["id"] == "eo:robot/bx2":
                e["serial"] = "TI5-T170C-001"
    ok, _ = validate_entities(_bad(m))
    assert not ok, "serial 重复应被唯一键形状拦截"


def test_l1_rejects_capability_without_provider():
    def m(es):
        es.append({"id": "eo:cap/orphan", "type": "Capability", "label": "孤儿能力",
                   "code": "orphan", "created_at": "2026-11-20T08:00:00+08:00"})
    ok, _ = validate_entities(_bad(m))
    assert not ok, "无提供者的能力应被领域形状拦截"


def test_l1_rejects_unregistered_metric():
    def m(es):
        es.append({"id": "eo:point/1", "type": "TelemetryPoint", "label": "坏测点",
                   "entity_ref": "eo:part/ti5/wrist", "metric_code": "unknown",
                   "value": 1.0, "time": "2026-11-24T10:00:00+08:00",
                   "created_at": "2026-11-24T10:00:00+08:00"})
    ok, _ = validate_entities(_bad(m))
    assert not ok, "未注册测点应被领域形状拦截"


def test_l1_rejects_foreign_fault_part():
    def m(es):
        for e in es:
            if e["id"] == "eo:event/fault-001":
                e["affects_bodypart"] = "eo:part/bx2/head"
    ok, _ = validate_entities(_bad(m))
    assert not ok, "故障部件不属于上报机器人应被拦截"


# ---------------------------------------------------------------- 加载器
def test_loader_rejects_unknown_type():
    try:
        load_entities(MemoryStore(), [{"id": "eo:x", "type": "Nope"}])
        assert False, "未知 ObjectType 应报错"
    except ValueError:
        pass


def test_loader_rejects_abstract_type():
    try:
        load_entities(MemoryStore(), [{"id": "eo:x", "type": "Entity"}])
        assert False, "抽象类 Entity 应拒绝实例化"
    except ValueError:
        pass


def test_loader_rejects_dangling_link():
    store = MemoryStore()
    store.add_node("eo:t", "Task", {"label": "t"})
    try:
        load_entities(store, [{"id": "eo:t2", "type": "Task",
                               "requires_capability": ["eo:cap/missing"]}])
        assert False, "悬空 Link 应报错"
    except ValueError:
        pass


# ---------------------------------------------------------------- 规则引擎
def test_rules():
    store, _ = _load()
    facts, _ = forward_chain(store, DOMAIN_RULES)
    assert ("eo:object/cup", "graspable", True) in facts       # 演绎
    assert ("eo:object/egg", "needs_force_control", True) in facts
    assert ("eo:object/bottle", "needs_screw", True) in facts
    assert ("eo:object/cup-slip", "grip_factor", 1.5) in facts  # 规则
    assert ("eo:object/cup", "grip_factor", 1.0) in facts
    assert ("eo:task/carry-kettle", "over_torque", 0.6) in facts  # 约束库
    assert ("eo:task/carry-cup", "torque_ok", 0.09) in facts
    assert ("eo:task/push-box", "over_load", 30.0) in facts


# ---------------------------------------------------------------- 可达性
def test_reachability_ti5():
    store, _ = _load()
    r = check_reachability(store, "eo:task/grasp-egg")
    assert r.verdict == "feasible", r.problems
    assert any("force-control" in line and "✓" in line for line in r.proof)


def test_reachability_robot_scoping():
    store, _ = _load()
    # 豹小秘2 无手臂：端杯子不可达
    r = check_reachability(store, "eo:task/carry-cup-by-bx2")
    assert r.verdict == "infeasible"
    assert any("不属于指派机器人" in p for p in r.problems)
    # 语音引导是 bx2 的活：可达
    r2 = check_reachability(store, "eo:task/guide-visitor")
    assert r2.verdict == "feasible", r2.problems


# ---------------------------------------------------------------- 故障传播
def test_fault_event_propagation():
    store, _ = _load()
    impact = propagate_fault_event(store, "eo:event/fault-001")
    assert impact.faulty_parts == ["eo:part/ti5/six-axis-force"]
    assert impact.lost_capabilities == ["eo:cap/force-control"]
    assert set(impact.affected_tasks) == {"eo:task/grasp-egg", "eo:task/pinch-coin"}

    store.get_node("eo:part/ti5/six-axis-force").properties["health"] = "fault"
    assert root_cause(store, "eo:task/grasp-egg") == ["eo:part/ti5/six-axis-force"]
    r = check_reachability(store, "eo:task/grasp-egg")
    assert r.verdict == "infeasible"
    r2 = check_reachability(store, "eo:task/carry-cup")
    assert r2.verdict == "feasible"  # 依赖隔离


def test_fault_direct_propagation():
    store, _ = _load()
    impact = propagate_fault(store, "eo:part/ti5/dexterous-hand")
    assert "eo:cap/power-grasp" in impact.lost_capabilities
    assert "eo:task/carry-cup" in impact.affected_tasks


# ---------------------------------------------------------------- 动作拦截
def test_intercept_torque_container():
    store, _ = _load()
    hits = intercept_action(store, "eo:task/carry-kettle")
    assert [h.kind for h in hits] == ["torque"]
    assert "先倒水" in hits[0].rewrite or "倒水" in hits[0].rewrite


def test_intercept_load():
    store, _ = _load()
    kinds = [h.kind for h in intercept_action(store, "eo:task/push-box")]
    assert "torque" in kinds and "load" in kinds


def test_intercept_pose():
    store, _ = _load()
    hits = intercept_action(store, "eo:task/sit-down")
    assert any(h.kind == "pose" for h in hits)
    pose = next(h for h in hits if h.kind == "pose")
    assert "改写任务意义" in pose.rewrite


def test_intercept_surface():
    store, _ = _load()
    hits = intercept_action(store, "eo:task/carry-slip-cup")
    assert any(h.kind == "surface" for h in hits)
    assert intercept_action(store, "eo:task/carry-cup") == []


# ---------------------------------------------------------------- JSON-LD
def test_jsonld_roundtrip():
    store, _ = _load()
    doc = export_jsonld(store)
    back = from_jsonld_document(doc)
    assert len(back) == len(store.nodes())
    ids = {e["id"] for e in back}
    assert all(n.id in ids for n in store.nodes())

    task = next(e for e in back if e["id"] == "eo:task/grasp-egg")
    assert set(task["requires_capability"]) == {"eo:cap/power-grasp", "eo:cap/force-control"}
    assert task["assigned_to"] == "eo:robot/ti5"
    cup = next(e for e in back if e["id"] == "eo:object/cup")
    assert cup["has_handle"] is True and cup["weight_kg"] == 0.3


# ---------------------------------------------------------------- CRUD
def _crud():
    crud = OntologyCRUD()
    crud.load(copy.deepcopy(json.load(open(DATA, encoding="utf-8"))))
    return crud


PEN = {"id": "eo:object/pen", "type": "Object", "label": "笔",
       "weight_kg": 0.02, "surface": "dry", "created_at": "2026-11-24T10:00:00+08:00"}


def test_crud_create_and_get():
    c = _crud()
    c.create(dict(PEN))
    assert c.get("eo:object/pen")["label"] == "笔"
    assert c.validate().conforms


def test_crud_rejects_duplicate_id():
    c = _crud()
    c.create(dict(PEN))
    try:
        c.create(dict(PEN))
        assert False, "重复 id 应拒绝"
    except CRUDError:
        pass


def test_crud_rejects_unknown_type():
    try:
        _crud().create({"id": "eo:x", "type": "Nope", "label": "x"})
        assert False, "未知 ObjectType 应拒绝"
    except CRUDError:
        pass


def test_crud_rejects_bad_value_and_rolls_back():
    c = _crud()
    before = c.get("eo:object/cup")["surface"]
    try:
        c.set_property("eo:object/cup", "surface", "wet")
        assert False, "枚举越界应被 Gate A 拒绝"
    except CRUDValidationError as e:
        assert e.report.violations, "应携带结构化违规报告"
    assert c.get("eo:object/cup")["surface"] == before, "拒绝后状态应回滚"


def test_crud_property_set_unset():
    c = _crud()
    c.set_property("eo:object/cup", "weight_kg", 0.35)
    assert c.get_property("eo:object/cup", "weight_kg") == 0.35
    c.unset_property("eo:object/cup", "weight_kg")
    assert c.get_property("eo:object/cup", "weight_kg") is None
    assert c.validate().conforms


def test_crud_link_replaces_single_value():
    c = _crud()
    c.link("eo:task/carry-cup", "eo:robot/bx2", "assigned_to")
    assert c.get("eo:task/carry-cup")["assigned_to"] == "eo:robot/bx2"
    c.unlink("eo:task/carry-cup", "eo:robot/bx2", "assigned_to")
    assert c.get("eo:task/carry-cup").get("assigned_to") is None


def test_crud_link_validations():
    c = _crud()
    try:
        c.link("eo:robot/ti5", "eo:part/ghost", "has_part")
        assert False, "目标不存在应拒绝"
    except CRUDError:
        pass
    try:
        c.link("eo:object/cup", "eo:robot/ti5", "weight_kg")
        assert False, "非 Link 槽应拒绝"
    except CRUDError:
        pass


def test_crud_delete_soft_and_physical():
    c = _crud()
    # 软删除：deprecated 标记，list 过滤、get 仍在
    c.create(dict(PEN))
    c.delete("eo:object/pen")
    assert c.get("eo:object/pen")["deprecated"] is True
    assert all(e["id"] != "eo:object/pen" for e in c.list())
    # 物理删除有引用者：Gate A 拒绝（悬空引用）
    try:
        c.delete("eo:cap/power-grasp", physical=True)
        assert False, "有引用者的物理删除应被拒绝"
    except CRUDValidationError as e:
        assert e.report.violations
    assert c.get("eo:cap/power-grasp") is not None, "拒绝后状态应回滚"
    # 无引用者：物理删除成功
    c.delete("eo:object/pen", physical=True)
    assert c.get("eo:object/pen") is None


def test_crud_update_immutable_fields():
    c = _crud()
    try:
        c.update("eo:object/cup", {"type": "Robot"})
        assert False, "类型不可变更"
    except CRUDError:
        pass
    try:
        c.update("eo:object/cup", {"id": "eo:x"})
        assert False, "id 不可变更"
    except CRUDError:
        pass


# ---------------------------------------------------------------- 时序绑定
def test_binding_read_and_snapshot():
    store, _ = _load()
    ts = SqliteTelemetryStore(":memory:")
    ts.insert("eo:robot/ti5", "battery", 86.0, "2026-11-24T10:00:00")
    ts.insert("eo:part/ti5/six-axis-force", "force_reading", 4.0, "2026-11-24T10:00:01")
    reg = BindingRegistry(store, ts)
    assert not reg.validate_bindings(), reg.validate_bindings()
    assert reg.read("eo:robot/ti5", "current_battery") == 86.0
    snap = reg.snapshot("eo:part/ti5/six-axis-force")
    assert snap.get("current_force") == 4.0
    assert reg.read("eo:robot/ti5", "no_such_slot") is None


def test_binding_rejects_bad_binds_to():
    store, _ = _load()
    # 篡改一条注册表：binds_to 指向目标类不存在的槽
    metric = store.get_node("eo:metric/battery")
    metric.properties["binds_to"] = "no_such_slot"
    reg = BindingRegistry(store, SqliteTelemetryStore(":memory:"))
    errs = reg.validate_bindings()
    assert any("no_such_slot" in e for e in errs)


# ---------------------------------------------------------------- 规则框架
def test_rule_engine_explain():
    store, _ = _load()
    eng = RuleEngine(store)
    eng.add_rules(DOMAIN_RULES)
    eng.run()
    text = eng.explain("eo:task/carry-kettle", "over_torque")
    assert "torque_constraint" in text and "kettle" in text


def test_rule_priority_dedup():
    store, _ = _load()
    eng = RuleEngine(store)

    def low(ctx: RuleContext):
        ctx.assert_(store.nodes()[0].id, "p", "low")

    def high(ctx: RuleContext):
        ctx.assert_(store.nodes()[0].id, "p", "high")

    eng.add_rule(RuleSpec("low", "", category="deduction", priority=10, fire=low))
    eng.add_rule(RuleSpec("high", "", category="deduction", priority=999, fire=high))
    eng.run()
    assert eng.facts[(store.nodes()[0].id, "p")].v == "high", "高优先级规则先断言并胜出"


def test_rule_action_binding():
    """监测规则断言 → 声明式动作绑定 → knowledge.writeback 写回本体。"""
    crud = _crud()
    reg = build_registry(crud)
    store = crud.store
    eng = RuleEngine(store, actions=reg)

    def monitor(ctx: RuleContext):
        ctx.assert_("eo:object/cup", "slip", True, evidence=["测试"])

    eng.add_rule(RuleSpec(
        "slip_monitor", "", category="monitoring", priority=50, fire=monitor,
        actions=[{"action": "knowledge.writeback",
                  "params": {"entity_id": "{s}", "patch": {"surface": "slippery"}}}],
    ))
    eng.run()
    assert crud.get("eo:object/cup")["surface"] == "slippery"
    assert any("eo:log/action-" in eid for eid in crud.entities)


# ---------------------------------------------------------------- Action 模型
def test_action_dispatch():
    crud = _crud()
    reg = build_registry(crud)
    result = reg.execute("task.dispatch", actor="test", task_id="eo:task/carry-cup")
    assert result.ok and result.audit_log_id
    task = crud.get("eo:task/carry-cup")
    assert task["status"] == "executing" and task["verdict"] == "feasible"
    # 审计已落库且过 Gate A
    assert crud.get(result.audit_log_id)["action_type"] == "task.dispatch"


def test_action_infeasible_dispatch():
    crud = _crud()
    reg = build_registry(crud)
    result = reg.execute("task.dispatch", actor="test", task_id="eo:task/carry-cup-by-bx2")
    assert result.ok  # 动作本身成功执行（业务结论是不可达）
    assert crud.get("eo:task/carry-cup-by-bx2")["status"] == "failed"
    assert any("不可达" in m for m in result.messages)


def test_action_rejections():
    crud = _crud()
    reg = build_registry(crud)
    # 目标不存在
    r1 = reg.execute("task.dispatch", actor="test", task_id="eo:task/ghost")
    assert not r1.ok and "不存在" in r1.messages[0]
    # 目标类型不符（mode_id 指向非 FaultMode）
    r2 = reg.execute("fault.report", actor="test", mode_id="eo:object/cup")
    assert not r2.ok
    # 改派目标不是 Robot
    r3 = reg.execute("task.reassign", actor="test", task_id="eo:task/carry-cup",
                     robot_id="eo:object/cup")
    assert not r3.ok
    # 写回坏值 → Gate A 拒绝 → 动作失败 + 审计 result=failed
    r4 = reg.execute("knowledge.writeback", actor="test", entity_id="eo:object/cup",
                     patch={"surface": "wet"})
    assert not r4.ok
    audit = crud.get(r4.audit_log_id)
    assert audit["result"] == "failed"
    # 缺参数
    r5 = reg.execute("task.dispatch", actor="test")
    assert not r5.ok and "缺少参数" in r5.messages[0]


def test_action_audit_seq_no_collision():
    """跨注册表实例执行：审计 id 从库中续号，不冲突。"""
    crud = _crud()
    r1 = build_registry(crud).execute("task.dispatch", actor="a", task_id="eo:task/carry-cup")
    r2 = build_registry(crud).execute("task.dispatch", actor="b", task_id="eo:task/carry-cup")
    assert r1.audit_log_id != r2.audit_log_id
    assert crud.get(r1.audit_log_id) and crud.get(r2.audit_log_id)


# ---------------------------------------------------------------- 时序库
def test_telemetry():
    ts = SqliteTelemetryStore(":memory:")
    ts.insert("eo:part/ti5/six-axis-force", "force_reading", 12.0, "2026-11-24T10:00:00")
    ts.insert("eo:part/ti5/six-axis-force", "force_reading", 4.0, "2026-11-24T10:00:01")
    ts.insert("eo:robot/ti5", "battery", 86.0, "2026-11-24T10:00:00")

    rows = ts.query(entity_ref="eo:part/ti5/six-axis-force", metric="force_reading")
    assert [r.value for r in rows] == [12.0, 4.0]
    assert ts.last("eo:part/ti5/six-axis-force", "force_reading").value == 4.0
    assert ts.last("eo:robot/ti5", "battery").value == 86.0
    assert len(ts.query()) == 3


def main():
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
