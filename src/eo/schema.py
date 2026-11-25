# -*- coding: utf-8 -*-
"""LinkML Schema 运行时访问层。

schema/embodied_ontology.yaml 是单一事实来源（TBox）；
本模块用 linkml_runtime.SchemaView 解析它，向下游（图加载器 / JSON-LD / SHACL）
提供「哪些是标量属性、哪些是 Link（对象槽）、枚举值、数值下限」等元信息。
"""
from __future__ import annotations

import os
from typing import List, Optional, Set

_SCHEMA_FILE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "schema", "embodied_ontology.yaml"))

_sv_cache = {}


def schema_view(path: Optional[str] = None):
    """惰性加载并缓存 SchemaView（默认主本体 Schema；path 可指向能力视图等其他 Schema）。"""
    key = path or _SCHEMA_FILE
    if key not in _sv_cache:
        from linkml_runtime.utils.schemaview import SchemaView

        _sv_cache[key] = SchemaView(key)
    return _sv_cache[key]


def all_classes() -> List[str]:
    """全部 ObjectType 名。"""
    return sorted(schema_view().all_classes().keys())


def all_slots() -> List[str]:
    """全部槽（Property + Link）名。"""
    return sorted(schema_view().all_slots().keys())


def class_slots(class_name: str) -> List[str]:
    """含继承（induced）的槽名列表。"""
    slots = schema_view().class_induced_slots(class_name)
    if isinstance(slots, dict):  # 兼容旧版 linkml-runtime
        return sorted(slots.keys())
    return sorted(s.name for s in slots)


def is_link_slot(class_name: str, slot_name: str) -> bool:
    """range 指向类（而非标量/枚举）的槽 = Link。"""
    sv = schema_view()
    try:
        slot = sv.induced_slot(slot_name, class_name)
    except Exception:
        slot = sv.get_slot(slot_name)
    return slot is not None and slot.range in sv.all_classes()


def link_slots(class_name: str) -> List[str]:
    return [s for s in class_slots(class_name) if is_link_slot(class_name, s)]


def scalar_slots(class_name: str) -> List[str]:
    return [s for s in class_slots(class_name) if not is_link_slot(class_name, s)]


def all_link_slots() -> Set[str]:
    out: Set[str] = set()
    for c in all_classes():
        out.update(link_slots(c))
    return out


def slot_range(slot_name: str) -> Optional[str]:
    sv = schema_view()
    try:
        slot = sv.get_slot(slot_name)
    except Exception:
        slot = sv.schema.slots.get(slot_name)
    return slot.range if slot else None


def enum_values(enum_name: str) -> List[str]:
    sv = schema_view()
    e = sv.get_enum(enum_name)
    return sorted(e.permissible_values.keys()) if e else []


def type_minimum(range_name: str) -> Optional[float]:
    """自定义标量类型的数值下限（如 mass_kg ≥ 0）。"""
    sv = schema_view()
    t = sv.schema.types.get(range_name)
    if t is not None:
        return getattr(t, "minimum_value", None)
    return None


def is_datetime_range(range_name: Optional[str]) -> bool:
    """range 是否为时间类型（内建 datetime 或自定义 timestamp 等 typeof=datetime 类型）。"""
    if range_name is None:
        return False
    if range_name == "datetime":
        return True
    sv = schema_view()
    t = sv.schema.types.get(range_name)
    return bool(t is not None and getattr(t, "typeof", None) == "datetime")


def concrete_classes() -> List[str]:
    """非抽象类（可实例化的 ObjectType）。"""
    sv = schema_view()
    return [c for c in all_classes()
            if not getattr(sv.get_class(c), "abstract", False)]


def default_prefix_name() -> str:
    return schema_view().schema.default_prefix or "eo"


def default_prefix_iri() -> str:
    sv = schema_view()
    pfx = sv.schema.default_prefix or "eo"
    p = sv.schema.prefixes.get(pfx)
    if p is None:
        return "https://example.org/embodied-ontology/"
    return getattr(p, "prefix_reference", p)
