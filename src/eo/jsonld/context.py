# -*- coding: utf-8 -*-
"""JSON-LD @context：由 LinkML Schema 自动推导（术语 → IRI 映射）。

默认推导主本体 Schema（embodied_ontology.yaml）；传入其他 SchemaView
（如能力视图 capability_view.yaml）即可推导对应 @context。

- 前缀与 @vocab 取自 schema 的 prefixes / default_prefix
- id → @id、type → @type（关键字别名）
- Link 槽（range 指向类）加 "@type": "@id"（值按 IRI 解释）
- datetime 槽（含 typeof=datetime 的自定义类型）加 "xsd:dateTime" 强制
"""
from __future__ import annotations

from typing import Any, Dict

from ..schema import schema_view


def _is_datetime(sv, range_name) -> bool:
    if range_name == "datetime":
        return True
    t = sv.schema.types.get(range_name)
    return bool(t is not None and getattr(t, "typeof", None) == "datetime")


def build_context(sv=None) -> Dict[str, Any]:
    """由 LinkML Schema 自动推导 JSON-LD @context。"""
    sv = sv or schema_view()
    ctx: Dict[str, Any] = {}

    for pfx, p in sv.schema.prefixes.items():
        ctx[pfx] = getattr(p, "prefix_reference", p)

    default_pfx = sv.schema.default_prefix or "eo"
    ctx["@vocab"] = ctx.get(default_pfx, "https://ontology.huilun.cn/embodied/")
    ctx["id"] = "@id"
    ctx["type"] = "@type"

    # Link 槽集合：range 指向类（含抽象基类）
    link_set = set()
    for cls in sv.all_classes().values():
        for s in sv.class_induced_slots(cls.name):
            if s.range in sv.all_classes():
                link_set.add(s.name)

    for slot_name, slot in sv.all_slots().items():
        if slot_name in ("id", "type"):
            continue
        term = f"{default_pfx}:{slot_name}"
        if slot_name in link_set:
            ctx[slot_name] = {"@id": term, "@type": "@id"}
        elif _is_datetime(sv, slot.range):
            ctx[slot_name] = {"@id": term, "@type": "xsd:dateTime"}
        else:
            ctx[slot_name] = term
    return ctx
