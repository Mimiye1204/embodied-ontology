# -*- coding: utf-8 -*-
"""本体 CRUD 命令行：Object / Property / Link 操作，全部经 Gate A 校验。

用法示例：
  python cli.py get eo:robot/ti5
  python cli.py list --type Task
  python cli.py create '{"id":"eo:object/pen","type":"Object","label":"笔","weight_kg":0.02,"surface":"dry","created_at":"2026-11-24T10:00:00+08:00"}'
  python cli.py update eo:object/pen '{"weight_kg": 0.03}'
  python cli.py set eo:object/pen surface '"rough"'          # 值按 JSON 解析
  python cli.py unset eo:object/pen surface
  python cli.py link eo:robot/ti5 eo:part/ti5/new-part has_part
  python cli.py unlink eo:task/carry-cup eo:robot/ti5 assigned_to
  python cli.py delete eo:object/pen [--physical]
  python cli.py validate
  python cli.py export [--out generated/now.jsonld]

状态文件：--file（默认 state/ontology.json；不存在时从 examples/fleet.json 初始化）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, List, Optional

from .crud import CRUDError, OntologyCRUD, ValidationError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_STATE = os.path.join(ROOT, "state", "ontology.json")
INITIAL_DATA = os.path.join(ROOT, "examples", "fleet.json")


def _parse_json(s: str) -> Any:
    if s.startswith("@"):  # @file.json
        with open(s[1:], encoding="utf-8") as f:
            return json.load(f)
    return json.loads(s)


def _load(args) -> OntologyCRUD:
    crud = OntologyCRUD()
    if os.path.exists(args.file):
        with open(args.file, encoding="utf-8") as f:
            entities = json.load(f)
    else:
        with open(INITIAL_DATA, encoding="utf-8") as f:
            entities = json.load(f)
        print(f"[state] {args.file} 不存在，从 examples/fleet.json 初始化")
    crud.load(entities)
    return crud


def _save(crud: OntologyCRUD, args) -> None:
    os.makedirs(os.path.dirname(args.file), exist_ok=True)
    with open(args.file, "w", encoding="utf-8") as f:
        json.dump(list(crud.entities.values()), f, ensure_ascii=False, indent=2)


def _run(crud: OntologyCRUD, args, fn, save: bool = True, ok_msg: Optional[str] = None) -> int:
    try:
        fn()
    except CRUDError as e:
        print(f"✗ 操作拒绝：{e}")
        return 1
    except ValidationError as e:
        print(e.report)
        print("✗ 写操作未落地（状态不变）")
        return 1
    if save:
        _save(crud, args)
    if ok_msg:
        print(ok_msg)
    return 0


def cmd_get(crud, args) -> int:
    def fn():
        ent = crud.get(args.id)
        if ent is None:
            print(f"✗ 实体 {args.id} 不存在")
        else:
            print(json.dumps(ent, ensure_ascii=False, indent=2))
    return _run(crud, args, fn, save=False)


def cmd_list(crud, args) -> int:
    def fn():
        where = {}
        if args.where:
            for kv in args.where.split(","):
                k, _, v = kv.partition("=")
                where[k.strip()] = _parse_json(v.strip())
        ents = crud.list(type=args.type, where=where)
        print(f"{len(ents)} 个实体：")
        for e in ents:
            print(f"  {e['id']:42s} {e['type']:16s} {e.get('label', '')}")
    return _run(crud, args, fn, save=False)


def cmd_create(crud, args) -> int:
    ent = _parse_json(args.entity)
    return _run(crud, args, lambda: crud.create(ent),
                ok_msg=f"✓ 已创建 {ent.get('id')}（{ent.get('type')}）")


def cmd_update(crud, args) -> int:
    return _run(crud, args, lambda: crud.update(args.id, _parse_json(args.patch)),
                ok_msg=f"✓ 已更新 {args.id}")


def cmd_set(crud, args) -> int:
    return _run(crud, args, lambda: crud.set_property(args.id, args.slot, _parse_json(args.value)),
                ok_msg=f"✓ 已设置 {args.id}.{args.slot}")


def cmd_unset(crud, args) -> int:
    return _run(crud, args, lambda: crud.unset_property(args.id, args.slot),
                ok_msg=f"✓ 已移除 {args.id}.{args.slot}")


def cmd_link(crud, args) -> int:
    return _run(crud, args, lambda: crud.link(args.src, args.dst, args.type),
                ok_msg=f"✓ 已建立 {args.src} --{args.type}--> {args.dst}")


def cmd_unlink(crud, args) -> int:
    return _run(crud, args, lambda: crud.unlink(args.src, args.dst, args.type),
                ok_msg=f"✓ 已移除 {args.src} --{args.type}--> {args.dst}")


def cmd_delete(crud, args) -> int:
    mode = "物理删除" if args.physical else "软删除（deprecated）"
    return _run(crud, args, lambda: crud.delete(args.id, physical=args.physical),
                ok_msg=f"✓ 已删除 {args.id}（{mode}）")


def cmd_validate(crud, args) -> int:
    report = crud.validate()
    print(report)
    return 0 if report.conforms else 1


def cmd_export(crud, args) -> int:
    path = args.out or os.path.join(ROOT, "generated", "current.jsonld")
    types = args.types.split(",") if args.types else None
    ids = args.ids.split(",") if args.ids else None
    doc = crud.export_jsonld(path, types=types, ids=ids)
    print(f"已导出 {path}（{len(doc['@graph'])} 个实体"
          + (f"，types={types}" if types else "")
          + (f"，ids 切片" if ids else "") + "）")
    return 0


def cmd_view(crud, args) -> int:
    from .views import build_capability_view, view_as_jsonld
    view = build_capability_view(crud.store, robot_id=args.robot)
    if args.jsonld:
        doc = view_as_jsonld(view)
        out = json.dumps(doc, ensure_ascii=False, indent=2)
    else:
        out = json.dumps(view, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"已导出能力视图 → {args.out}")
    else:
        print(out)
    return 0


def cmd_action_list(crud, args) -> int:
    from .actions import build_registry
    reg = build_registry(crud)
    for a in reg.list():
        print(f"  {a['name']:22s} {a['description']}")
        print(f"       params={a['params']}  targets={a['targets']}")
    return 0


def cmd_intercept(crud, args) -> int:
    from .rules import intercept_report
    report = intercept_report(crud.store, args.id)
    if report.allowed:
        print(f"✓ {args.id} 无拦截，放行执行")
    else:
        print(f"⛔ {args.id} 触发 {len(report.interceptions)} 项拦截：")
        for h in report.interceptions:
            print(f"  [{h.kind}] {h.reason}")
            print(f"      → 改写：{h.rewrite}")
    return 0


def cmd_path(crud, args) -> int:
    from .graph.traversal import format_path, shortest_path
    path = shortest_path(crud.store, args.src, args.dst)
    if path is None:
        print(f"✗ {args.src} 与 {args.dst} 之间无路径")
        return 1
    print(f"最短路径（{len(path)} 条边）：")
    print("  " + format_path(path))
    return 0


def cmd_action(crud, args) -> int:
    from .actions import build_registry
    reg = build_registry(crud)
    params = _parse_json(args.params)
    result = reg.execute(args.action, actor=args.actor or "cli", **params)
    if result is None:
        print(f"✗ 未知动作 {args.action}（用 action-list 查看）")
        return 1
    for m in result.messages:
        print(f"  {m}")
    if not result.ok:
        return 1
    _save(crud, args)
    print(f"✓ {result.action} 完成（审计 {result.audit_log_id}）")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="具身本体论 · Object/Property/Link CRUD")
    parser.add_argument("--file", default=DEFAULT_STATE, help="状态文件（JSON）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("get", help="读实体"); p.add_argument("id")
    p = sub.add_parser("list", help="列实体")
    p.add_argument("--type", help="ObjectType 过滤")
    p.add_argument("--where", help="属性等值过滤，如 status=\"pending\"")
    p = sub.add_parser("create", help="新建实体（JSON 或 @file）"); p.add_argument("entity")
    p = sub.add_parser("update", help="更新实体（补丁 JSON）")
    p.add_argument("id"); p.add_argument("patch")
    p = sub.add_parser("set", help="设置属性（值按 JSON 解析）")
    p.add_argument("id"); p.add_argument("slot"); p.add_argument("value")
    p = sub.add_parser("unset", help="移除属性"); p.add_argument("id"); p.add_argument("slot")
    p = sub.add_parser("link", help="建立关系"); p.add_argument("src"); p.add_argument("dst"); p.add_argument("type")
    p = sub.add_parser("unlink", help="移除关系"); p.add_argument("src"); p.add_argument("dst", nargs="?")
    p.add_argument("--type")
    p = sub.add_parser("delete", help="删除实体")
    p.add_argument("id"); p.add_argument("--physical", action="store_true", help="物理删除（默认软删除）")
    sub.add_parser("validate", help="全量校验（Gate C）")
    p = sub.add_parser("export", help="导出 JSON-LD（支持过滤切片）")
    p.add_argument("--out")
    p.add_argument("--types", help="只导出这些 ObjectType（逗号分隔）")
    p.add_argument("--ids", help="只导出这些实体 id（含引用闭包）")
    p = sub.add_parser("view", help="导出本体能力视图（给调度中台）")
    p.add_argument("--robot", help="只含指定机器人")
    p.add_argument("--jsonld", action="store_true", help="输出 JSON-LD（否则纯 JSON）")
    p.add_argument("--out")
    sub.add_parser("action-list", help="列出受控动作（ActionType 注册表）")
    p = sub.add_parser("action", help="执行受控动作")
    p.add_argument("action"); p.add_argument("params", help="参数 JSON")
    p.add_argument("--actor", default="cli")
    p = sub.add_parser("intercept", help="动作拦截检查（Gate B）"); p.add_argument("id")
    p = sub.add_parser("path", help="两点最短路径查询")
    p.add_argument("src"); p.add_argument("dst")

    args = parser.parse_args(argv)
    try:
        crud = _load(args)
    except ValidationError as e:
        print(e.report)
        return 1

    handlers = {
        "get": cmd_get, "list": cmd_list, "create": cmd_create, "update": cmd_update,
        "set": cmd_set, "unset": cmd_unset, "link": cmd_link, "unlink": cmd_unlink,
        "delete": cmd_delete, "validate": cmd_validate, "export": cmd_export,
        "action": cmd_action, "action-list": cmd_action_list,
        "intercept": cmd_intercept, "path": cmd_path, "view": cmd_view,
    }
    return handlers[args.cmd](crud, args)


if __name__ == "__main__":
    sys.exit(main())
