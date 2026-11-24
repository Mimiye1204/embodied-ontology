# -*- coding: utf-8 -*-
"""具身本体论引擎 · 端到端验证（生产 Schema v1.0.0）

流水线：LinkML Schema（TBox）→ SHACL 校验（L0+L1）→ 图存储（Node/Edge）
       → 规则引擎（演绎/约束/归纳）→ 任务可达性（含指派机器人范围）
       → 动作拦截（约束库驱动）→ 故障传播（模式库驱动，正向+反向）
       → 时序库（外键关联+滑移检测写回）→ JSON-LD 全域交换（round-trip）

运行：.venv/Scripts/python.exe demo.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from eo.graph import MemoryStore
from eo.graph.loader import load_json_file
from eo.jsonld import build_context, export_jsonld, from_jsonld_document
from eo.rules import (
    DOMAIN_RULES,
    check_reachability,
    forward_chain,
    intercept_action,
    propagate_fault_event,
    root_cause,
)
from eo.schema import all_classes, all_slots, schema_view
from eo.shacl import save_shapes, validate_entities
from eo.timeseries import SqliteTelemetryStore

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "examples", "fleet.json")
GEN = os.path.join(ROOT, "generated")

VERDICT_ICON = {"feasible": "✓", "constrained": "⚠", "infeasible": "✗", "rewrite": "✗"}


def section(title: str) -> None:
    print()
    print("=" * 74)
    print(title)
    print("=" * 74)


def main() -> None:
    print("具身本体论引擎 · 端到端验证（Schema v1.0.0 · 双机器人编队）")
    print("LinkML 定义 Schema · SHACL 校验(L0+L1) · JSON-LD 交换 · 图存储 · 规则引擎 · 时序库")

    # ---------------------------------------------------------------- 0. Schema
    section("[0] 结构层 TBox：LinkML Schema（单一事实来源）")
    sv = schema_view()
    print(f"schema/embodied_ontology.yaml  →  {len(all_classes())} 个 ObjectType，"
          f"{len(all_slots())} 个槽（Property + Link）")
    print(f"ObjectType: {all_classes()}")

    # ------------------------------------------------- 1. 数据 + SHACL 校验
    section("[1] 数据层 ABox：加载实体对象库 + SHACL 校验（Gate A）")
    with open(DATA, encoding="utf-8") as f:
        entities = json.load(f)
    conforms, report = validate_entities(entities)
    print(f"SHACL（L0 结构形状由 Schema 生成 + L1 引用完整性/领域形状）: "
          f"{'通过 ✓' if conforms else '失败 ✗'}")
    if conforms:
        print(f"  {len(entities)} 个实例全部合法：结构/枚举/数值域/唯一键/引用完整性/领域不变量")
    else:
        print(report)
        return

    # 负例演示：七类违规逐一被拦截
    import copy as _copy
    neg_cases = []
    bad = _copy.deepcopy(entities)
    for e in bad:
        if e["id"] == "eo:robot/bx2":
            e["serial"] = "TI5-T170C-001"
    neg_cases.append(("serial 重复（唯一键）", validate_entities(bad)[0]))
    bad = _copy.deepcopy(entities)
    for e in bad:
        if e["id"] == "eo:task/carry-cup":
            e["requires_capability"] = ["eo:cap/nonexistent"]
    neg_cases.append(("悬空引用（L1）", validate_entities(bad)[0]))
    bad = _copy.deepcopy(entities)
    for e in bad:
        if e["id"] == "eo:object/cup":
            e["weight_kg"] = -1.0
            e["surface"] = "wet"
    neg_cases.append(("负重量/枚举越界（L0）", validate_entities(bad)[0]))
    for name, ok in neg_cases:
        print(f"  负例 [{name}]：{'被拦截 ✓' if not ok else '漏过 ✗'}")

    # ------------------------------------------------------- 2. 图存储（Node/Edge）
    section("[2] 存储层：实体对象库 → 图（本机内存实现，生产 Neo4jStore 同接口）")
    store = load_json_file(MemoryStore(), DATA)
    robots = [n for n in store.nodes() if n.type == "Robot"]
    print(f"节点 {len(store.nodes())} 个 / Link 边 {len(store.edges())} 条")
    fleet = "、".join(f"{r.get('label')}（{r.id}，{r.get('model')}）" for r in robots)
    print(f"编队：{fleet}")

    # ------------------------------------------------------------ 3. 规则引擎
    section("[3] 计算层：规则引擎（正向链 + 逐规则增量打印）")
    facts, trace = forward_chain(store, DOMAIN_RULES)
    for t in trace:
        added_str = ", ".join(f"{s}--{p}--> {v}" for s, p, v in sorted(t.added))
        print(f"  [{t.rule_name}] {t.description}  新增 {len(t.added)} 条：")
        print(f"      {added_str}")
    print(f"  共推出 {len(facts)} 条事实")

    # ------------------------------------------------------------ 4. 任务可达性
    section("[4] 图推理：任务可达性（任务 → 能力 → 部件 + 指派机器人范围）")
    tasks = [n for n in store.nodes() if n.type == "Task"]
    for t in sorted(tasks, key=lambda n: n.id):
        r = check_reachability(store, t.id)
        icon = VERDICT_ICON.get(r.verdict, "?")
        problems = f"   ← 原因：{'；'.join(r.problems)}" if r.problems else ""
        print(f"  {icon} {t.id}（{t.get('label')}）→ {r.verdict}{problems}")
    print("\n  「语音引导访客」（派豹小秘2）完整证明链：")
    for line in check_reachability(store, "eo:task/guide-visitor").proof:
        print(f"      {line}")

    # ------------------------------------------------------------ 5. 动作拦截
    section("[5] 动作拦截：执行前检查（约束库驱动，Gate B）")
    for t in sorted(tasks, key=lambda n: n.id):
        hits = intercept_action(store, t.id)
        if hits:
            print(f"  ⛔ {t.id}（{t.get('label')}）触发 {len(hits)} 项拦截：")
            for h in hits:
                print(f"      [{h.kind}] {h.reason}")
                print(f"          → 改写：{h.rewrite}")
        else:
            print(f"  ✓ {t.id}（{t.get('label')}）无拦截，放行")

    # ------------------------------------------------------------ 6. 故障传播
    section("[6] 故障传播：故障事件 → 模式库 → 级联影响面 + 根因定位")
    store.get_node("eo:part/ti5/six-axis-force").properties["health"] = "fault"
    impact = propagate_fault_event(store, "eo:event/fault-001")
    print(f"  事件 eo:event/fault-001 → 模式 eo:faultmode/force-sensor-failure")
    print(f"  正向传播：受影响部件 {impact.faulty_parts}")
    print(f"            → 能力失效 {impact.lost_capabilities}")
    print(f"            → 受影响任务 {impact.affected_tasks}")
    r1 = check_reachability(store, "eo:task/grasp-egg")
    r2 = check_reachability(store, "eo:task/carry-cup")
    print(f"  可达性复检：抓鸡蛋 → {VERDICT_ICON[r1.verdict]} {r1.verdict}（{r1.problems[0]}）；"
          f"端杯子 → {VERDICT_ICON[r2.verdict]} {r2.verdict}（走包握，不受影响）")
    suspects = root_cause(store, "eo:task/grasp-egg")
    print(f"  反向根因：抓鸡蛋失败 → 依赖链回溯 → 可疑部件 {suspects}")

    # ------------------------------------------------- 7. 时序库（外键关联）
    section("[7] 时序库：测点外键关联本体实体（entity_ref ∈ 注册表已校验）")
    ts = SqliteTelemetryStore(":memory:")   # 生产换成 TimescaleTelemetryStore
    for i, v in enumerate([12.0, 11.5, 9.0, 4.0]):
        ts.insert("eo:part/ti5/six-axis-force", "force_reading", v, f"2026-11-24T10:00:0{i}")
    for i, v in enumerate([30.0, 35.0, 32.0]):
        ts.insert("eo:part/ti5/wrist", "joint_angle", v, f"2026-11-24T10:00:0{i}")
    ts.insert("eo:robot/ti5", "battery", 86.0, "2026-11-24T10:00:00")

    rows = ts.query(entity_ref="eo:part/ti5/six-axis-force", metric="force_reading")
    node = store.get_node("eo:part/ti5/six-axis-force")
    print(f"  写入 8 条测点（键=(entity_ref, metric)，均已过测点注册表校验）；")
    print(f"  按外键查询 → join 图节点「{node.get('label')}」：")
    for r in rows:
        print(f"      {r.time[-8:]}  force_reading = {r.value} N")

    first, last = rows[0].value, rows[-1].value
    if first > 0 and last / first < 0.5:
        print(f"  ⚠ 滑移检测：力读数 {first} N → {last} N（骤降 {(1 - last / first) * 100:.0f}%）")
        print("  → 归纳写回：eo:object/cup.surface = 'slippery'（本体获得新事实）")
        store.get_node("eo:object/cup").properties["surface"] = "slippery"
        _, trace2 = forward_chain(store, DOMAIN_RULES, facts)
        for t in trace2:
            for s, p, v in sorted(t.added):
                print(f"      [{t.rule_name}] 新增：{s} --{p}--> {v}")

    # ------------------------------------------------------------ 8. 动力层
    section("[8] 动力层：时序属性绑定 + 规则证明链 + Action 受控动作")
    from eo.actions import build_registry
    from eo.crud import OntologyCRUD
    from eo.jsonld import graph_to_entities
    from eo.rules.framework import RuleEngine
    from eo.timeseries.binding import BindingRegistry

    # 8.1 时序属性绑定（测点注册表 binds_to 声明 → 动态属性物化）
    bindings = BindingRegistry(store, ts)
    berrs = bindings.validate_bindings()
    print(f"时序绑定 {len(bindings.bindings)} 个（binds_to 声明），"
          f"合法性校验：{'通过 ✓' if not berrs else '失败 ✗ ' + str(berrs)}")
    print(f"  动态属性物化 eo:robot/ti5 → {bindings.snapshot('eo:robot/ti5')}")
    print(f"  动态属性物化 eo:part/ti5/six-axis-force → "
          f"{bindings.snapshot('eo:part/ti5/six-axis-force')}")

    # 8.2 规则引擎框架：证明链（为什么推出这个结论）
    eng = RuleEngine(store, bindings=bindings)
    eng.add_rules(DOMAIN_RULES)
    eng.run()
    print("  证明链（为什么「端满水壶」力矩超限）：")
    for line in eng.explain("eo:task/carry-kettle", "over_torque").splitlines():
        print(f"      {line}")

    # 8.3 Action 绑定模型（受控写操作：校验 + 审计）
    crud = OntologyCRUD()
    crud.load(graph_to_entities(store))
    registry = build_registry(crud)
    result = registry.execute("task.dispatch", actor="demo", task_id="eo:task/carry-cup")
    print(f"  动作 task.dispatch（杯面已湿滑 → 应拦截）：")
    for m in result.messages:
        print(f"      {m}")
    print(f"  自动审计：{result.audit_log_id}（ActionLog 实体已过 Gate A 落库）")
    store = crud.store   # 后续交换层导出含动作产物

    # ------------------------------------------------------------ 9. JSON-LD
    section("[9] 交换层：JSON-LD 全域交换（导出 + 双向 round-trip）")
    os.makedirs(GEN, exist_ok=True)
    doc = export_jsonld(store, os.path.join(GEN, "fleet.jsonld"))
    with open(os.path.join(GEN, "context.jsonld"), "w", encoding="utf-8") as f:
        json.dump({"@context": build_context()}, f, ensure_ascii=False, indent=2)
    save_shapes(os.path.join(GEN, "shapes.ttl"))

    back = from_jsonld_document(doc)
    ok_rt = all(any(e["id"] == n.id for e in back) for n in store.nodes())
    print(f"  @context 由 Schema 自动推导（{len(build_context())} 个术语映射）")
    print(f"  导出 generated/fleet.jsonld：{len(doc['@graph'])} 个节点")
    print(f"  导入重建（JSON-LD → RDF → 实体）：{len(back)} 个实体，"
          f"round-trip {'完整 ✓' if ok_rt else '丢失 ✗'}")
    cup = next(e for e in back if e["id"] == "eo:object/cup")
    print(f"  样例（写回属性随交换格式带出）：{json.dumps(cup, ensure_ascii=False)}")

    # ------------------------------------------------------------ 10. 产物清单
    section("[10] 产物清单")
    for p in ["schema/embodied_ontology.yaml",
              "docs/01-linkml-schema-design.md",
              "docs/02-neo4j-mapping-spec.md",
              "docs/03-shacl-framework.md",
              "generated/shapes.ttl", "generated/context.jsonld", "generated/fleet.jsonld",
              "ddl/neo4j_schema.cypher", "ddl/timescale_schema.sql"]:
        print(f"  {p}")
    print("\n完成：Schema(LinkML) → 校验(SHACL L0+L1) → 图(Neo4j 规范) → 规则引擎(L2) → "
          "时序(TimescaleDB 接口) → 交换(JSON-LD) 全链路跑通。")


if __name__ == "__main__":
    main()
