# -*- coding: utf-8 -*-
"""JSON-LD @context：由 LinkML Schema 自动推导（术语 → IRI 映射）。

- 前缀与 @vocab 取自 schema 的 prefixes / default_prefix
- id → @id、type → @type（关键字别名）
- Link 槽加 "@type": "@id"（值按 IRI 解释）
- datetime 槽加 "@type": "xsd:dateTime"（字符串自动带类型）
"""
from __future__ import annotations

from typing import Any, Dict

from ..schema import all_link_slots, all_slots, is_datetime_range, schema_view, slot_range


def build_context() -> Dict[str, Any]:
    sv = schema_view()
    ctx: Dict[str, Any] = {}

    for pfx, p in sv.schema.prefixes.items():
        ctx[pfx] = getattr(p, "prefix_reference", p)

    default_pfx = sv.schema.default_prefix or "eo"
    ctx["@vocab"] = ctx.get(default_pfx, "https://example.org/embodied-ontology/")
    ctx["id"] = "@id"
    ctx["type"] = "@type"

    link_set = all_link_slots()
    for slot_name in all_slots():
        if slot_name in ("id", "type"):
            continue
        term = f"{default_pfx}:{slot_name}"
        if slot_name in link_set:
            ctx[slot_name] = {"@id": term, "@type": "@id"}
        elif is_datetime_range(slot_range(slot_name)):
            ctx[slot_name] = {"@id": term, "@type": "xsd:dateTime"}
        else:
            ctx[slot_name] = term
    return ctx
