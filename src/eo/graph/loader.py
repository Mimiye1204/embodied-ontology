# -*- coding: utf-8 -*-
"""实体对象库加载器：JSON 清单（调研总结「方法B」）→ 图存储（Node/Edge）。

- ObjectType 由 LinkML Schema 校验（未知类型直接报错）
- 标量槽（Property）→ 节点属性
- 对象槽（Link）→ 图边
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from ..schema import concrete_classes, link_slots
from .base import GraphStore


def load_entities(store: GraphStore, entities: List[Dict[str, Any]]) -> GraphStore:
    # 第一遍：建节点（只保留标量属性；id/type 是节点身份）
    for e in entities:
        etype = e.get("type")
        if not etype:
            raise ValueError(f"实体缺少 type 字段: {e}")
        if etype not in concrete_classes():
            raise ValueError(f"未知/抽象 ObjectType '{etype}'（LinkML Schema 未定义或不可实例化）: {e}")
        if "id" not in e:
            raise ValueError(f"实体缺少 id 字段: {e}")
        props = {
            k: v for k, v in e.items()
            if k not in ("id", "type") and k not in link_slots(etype)
        }
        store.add_node(e["id"], etype, props)

    # 第二遍：建边（Link 槽 → 有向边）
    for e in entities:
        for slot in link_slots(e["type"]):
            targets = e.get(slot)
            if targets is None:
                continue
            if not isinstance(targets, list):
                targets = [targets]
            for t in targets:
                if not store.has_node(t):
                    raise ValueError(f"实体 {e['id']} 的 {slot} 指向不存在的节点 {t}")
                store.add_edge(e["id"], t, slot)
    return store


def load_json_file(store: GraphStore, path: str) -> GraphStore:
    with open(path, encoding="utf-8") as f:
        entities = json.load(f)
    return load_entities(store, entities)
