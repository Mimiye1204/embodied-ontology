# -*- coding: utf-8 -*-
"""生成浏览器可视化报告 generated/report.html，并在默认浏览器打开。

页面数据全部由引擎实时计算（正常态 + 故障态两份），嵌入单文件 HTML，
无外部依赖、离线可开。
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from eo.graph import MemoryStore
from eo.graph.loader import load_json_file
from eo.jsonld import export_jsonld
from eo.rules import (
    DOMAIN_RULES, check_reachability, forward_chain,
    intercept_action, propagate_fault_event, root_cause,
)
from eo.shacl import validate_entities
from eo.timeseries import SqliteTelemetryStore

ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(ROOT, "report_template.html")
OUT = os.path.join(ROOT, "generated", "report.html")


def main():
    data_path = os.path.join(ROOT, "examples", "fleet.json")
    with open(data_path, encoding="utf-8") as f:
        entities = json.load(f)

    # ---- SHACL ----
    conforms, _ = validate_entities(entities)
    bad = [dict(e, weight_kg=-1.0, surface="wet") if e.get("id") == "eo:object/cup" else e
           for e in entities]
    neg_conforms, _ = validate_entities(bad)

    # ---- 图 + 规则（正常态） ----
    store = load_json_file(MemoryStore(), data_path)
    facts, trace = forward_chain(store, DOMAIN_RULES)

    tasks = sorted([n for n in store.nodes() if n.type == "Task"], key=lambda n: n.id)
    task_states = {}
    for t in tasks:
        r = check_reachability(store, t.id)
        hits = intercept_action(store, t.id)
        assigned = store.out_neighbors(t.id, "assigned_to")
        task_states[t.id] = {
            "label": t.get("label"),
            "robot": assigned[0].id if assigned else None,
            "normal": {"verdict": r.verdict, "proof": r.proof, "problems": r.problems},
            "interceptions": [
                {"kind": h.kind, "reason": h.reason, "rewrite": h.rewrite} for h in hits
            ],
        }

    # ---- 故障态 ----
    store.get_node("eo:part/ti5/six-axis-force").properties["health"] = "fault"
    for t in tasks:
        r = check_reachability(store, t.id)
        task_states[t.id]["fault"] = {"verdict": r.verdict, "proof": r.proof, "problems": r.problems}
    impact = propagate_fault_event(store, "eo:event/fault-001")
    suspects = root_cause(store, "eo:task/grasp-egg")

    # ---- 时序 + 滑移写回（归纳闭环） ----
    ts = SqliteTelemetryStore(":memory:")
    for i, v in enumerate([12.0, 11.5, 9.0, 4.0]):
        ts.insert("eo:part/ti5/six-axis-force", "force_reading", v, f"2026-11-24T10:00:0{i}")
    rows = ts.query(entity_ref="eo:part/ti5/six-axis-force", metric="force_reading")
    drop_pct = round((rows[0].value - rows[-1].value) / rows[0].value * 100)
    store.get_node("eo:object/cup").properties["surface"] = "slippery"
    _, trace2 = forward_chain(store, DOMAIN_RULES, facts)

    # ---- 图数据（含事件节点） ----
    nodes = [
        {"id": n.id, "type": n.type, "label": n.get("label") or n.id,
         "health": n.get("health")}
        for n in sorted(store.nodes(), key=lambda x: x.id)
    ]
    edges = [{"src": e.src, "dst": e.dst, "type": e.type} for e in store.edges()]

    # ---- JSON-LD（最终态：含故障事件 + 湿滑写回） ----
    doc = export_jsonld(store)
    cup = next(e for e in doc["@graph"] if e["id"] == "eo:object/cup")

    data = {
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "rules": len(trace),
            "facts": len(facts),
            "jsonld": len(doc["@graph"]),
            "robots": len([n for n in nodes if n["type"] == "Robot"]),
            "tasks": len(tasks),
        },
        "nodes": nodes,
        "edges": edges,
        "tasks": task_states,
        "rules": [
            {"name": t.rule_name, "desc": t.description,
             "facts": [[s, p, str(v)] for s, p, v in sorted(t.added)]}
            for t in trace
        ],
        "writeback": [[s, p, str(v)] for t in trace2 for s, p, v in sorted(t.added)],
        "shacl": {"count": len(entities), "conforms": bool(conforms),
                  "neg_blocked": not neg_conforms},
        "fault": {
            "event": "eo:event/fault-001",
            "mode": "eo:faultmode/force-sensor-failure",
            "mode_label": "六维力传感器失效",
            "part": "eo:part/ti5/six-axis-force",
            "part_label": "六维力传感器",
            "lost_caps": impact.lost_capabilities,
            "affected": impact.affected_tasks,
            "suspects": suspects,
        },
        "telemetry": {
            "points": [{"t": r.time[-8:], "v": r.value} for r in rows],
            "drop_pct": drop_pct,
        },
        "jsonld": {"count": len(doc["@graph"]), "cup": cup},
    }

    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"报告已生成: {OUT}")
    subprocess.Popen(["cmd", "/c", "start", "", OUT])
    print("已在默认浏览器打开。")


if __name__ == "__main__":
    main()
