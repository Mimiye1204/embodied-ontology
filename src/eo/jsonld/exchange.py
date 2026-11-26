# -*- coding: utf-8 -*-
"""JSON-LD 全域交换格式：图 ↔ JSON-LD 文档双向转换（round-trip）。

导出：图存储（Node/Edge）→ JSON-LD 文档（@context + @graph）
导入：JSON-LD 文档 → RDF（rdflib）→ 实体 dict 列表 → 可重建图（语义无损验证）
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..graph.base import GraphStore
from ..schema import all_classes, all_slots, default_prefix_iri, default_prefix_name, link_slots
from .context import build_context

CONTEXT = build_context()


def to_jsonld_document(entities: List[Dict[str, Any]]) -> Dict[str, Any]:
    """实体 dict 列表 → JSON-LD 文档（@context 由 LinkML Schema 推导）。"""
    return {"@context": CONTEXT, "@graph": entities}


def graph_to_entities(store: GraphStore) -> List[Dict[str, Any]]:
    """图 → 实体 dict（Link 槽由边重建）。"""
    entities: List[Dict[str, Any]] = []
    for node in sorted(store.nodes(), key=lambda n: n.id):
        e: Dict[str, Any] = {"id": node.id, "type": node.type}
        for k, v in sorted(node.properties.items()):
            e[k] = v
        for slot in link_slots(node.type):
            targets = [n.id for n in store.out_neighbors(node.id, slot)]
            if targets:
                e[slot] = targets[0] if len(targets) == 1 else targets
        entities.append(e)
    return entities


def export_jsonld(store: GraphStore, path: Optional[str] = None,
                  types: Optional[List[str]] = None,
                  ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """图 → JSON-LD 文档；path 给定时落盘。

    支持过滤切片：
      types —— 只导出这些 ObjectType
      ids   —— 只导出这些实体 id + 其直接引用（一跳）的节点（聚焦切片）
    """
    entities = graph_to_entities(store)
    if types is not None:
        allowed = set(types)
        entities = [e for e in entities if e["type"] in allowed]
    if ids is not None:
        allowed = set(ids)
        keep = set(ids)
        for e in entities:
            if e["id"] not in allowed:
                continue
            for slot in link_slots(e["type"]):
                targets = e.get(slot)
                if targets:
                    keep.update(targets if isinstance(targets, list) else [targets])
        entities = [e for e in entities if e["id"] in keep]
    doc = to_jsonld_document(entities)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
    return doc


def to_rdf_graph(doc: Dict[str, Any]):
    """JSON-LD 文档 → rdflib RDF 图（供 SHACL 校验 / SPARQL / 语义查询）。"""
    from rdflib import Graph

    g = Graph()
    g.parse(data=json.dumps(doc, ensure_ascii=False), format="json-ld")
    return g


def compact_iri(iri: str) -> str:
    """完整 IRI → 前缀形式（eo:cup）；非本体的 IRI 原样返回。"""
    base = default_prefix_iri()
    if iri.startswith(base):
        return f"{default_prefix_name()}:{iri[len(base):]}"
    return iri


_compact = compact_iri  # 兼容旧引用


def from_jsonld_document(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """JSON-LD 文档 → 实体 dict 列表（经 RDF 中介，验证语义无损）。"""
    from rdflib import Literal, RDF, URIRef

    g = to_rdf_graph(doc)
    slot_of_iri = {default_prefix_iri() + s: s for s in all_slots()}
    classes = set(all_classes())
    by_id: Dict[str, Dict[str, Any]] = {}

    for subj in g.subjects():
        types = [str(t) for t in g.objects(subj, RDF.type)
                 if str(t).split("/")[-1] in classes]
        if not types:
            continue
        e: Dict[str, Any] = {
            "id": _compact(str(subj)),
            "type": str(types[0]).split("/")[-1],
        }
        for p, o in g.predicate_objects(subj):
            slot = slot_of_iri.get(str(p))
            if slot is None or slot == "id":
                continue
            if isinstance(o, Literal):
                val = o.toPython()
                if isinstance(val, datetime):
                    val = val.isoformat()  # 时间戳归一为 ISO 字符串（交换格式保真）
                e[slot] = val
            elif isinstance(o, URIRef):
                e.setdefault(slot, []).append(_compact(str(o)))
        # 单值 Link 拍平
        for k, v in list(e.items()):
            if isinstance(v, list) and len(v) == 1:
                e[k] = v[0]
        by_id[e["id"]] = e
    return list(by_id.values())
