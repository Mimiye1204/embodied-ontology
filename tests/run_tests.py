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
from eo.rules import (
    DOMAIN_RULES, check_reachability, forward_chain,
    intercept_action, propagate_fault, propagate_fault_event, root_cause,
)
from eo.shacl import validate_entities
from eo.timeseries import SqliteTelemetryStore

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
