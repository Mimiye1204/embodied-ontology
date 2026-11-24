# -*- coding: utf-8 -*-
"""由 LinkML Schema 自动生成 SHACL 形状（docs/03 校验框架的实现）。

L0 结构层（每类一个 NodeShape，closed）：
  required → sh:minCount / 枚举 → sh:in(RDF 列表) / 数值域 → sh:min|maxInclusive
  Link → sh:class（抽象基类 range 降级 sh:nodeKind IRI）
  unique_keys → SPARQL 唯一形状（模式 A）

L1 领域层（自动部分）：
  每个 Link 槽的引用完整性形状（模式 B，目标必须存在于数据集）

L1 手写部分见 domain.ttl（validate.py 合并）。
"""
from __future__ import annotations

from typing import List, Optional

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import RDF, XSD

from ..schema import (
    all_classes,
    class_slots,
    default_prefix_iri,
    enum_values,
    schema_view,
    type_minimum,
)

EO = Namespace(default_prefix_iri())
SH = Namespace("http://www.w3.org/ns/shacl#")

_BUILTIN_DATATYPES = {
    "boolean": XSD.boolean,
    "datetime": XSD.dateTime,
    "integer": XSD.integer,
    "float": XSD.double,
    "double": XSD.double,
    "decimal": XSD.decimal,
    "string": XSD.string,
}


def _sparql_constraint(g: Graph, shape: URIRef, message: str, select: str) -> None:
    """挂一个 SPARQL 约束（SELECT 每返回一行 = 一条违规；$this 由 pyshacl 预绑定）。"""
    node = BNode()
    g.add((shape, SH["sparql"], node))
    g.add((node, RDF.type, SH.SPARQLConstraint))
    g.add((node, SH["message"], Literal(message)))
    g.add((node, SH["prefixes"], URIRef(default_prefix_iri())))
    g.add((node, SH["select"], Literal(select)))


# ---------------------------------------------------------------- L0 ----------
def _emit_property_shape(g: Graph, shape: URIRef, class_name: str, slot_name: str) -> None:
    sv = schema_view()
    try:
        slot = sv.induced_slot(slot_name, class_name)
    except Exception:
        slot = sv.get_slot(slot_name)
    if slot is None:
        return

    if slot_name == "id":
        # 标识符在 JSON-LD 是节点自身 @id（IRI），存在性由 sh:nodeKind 保证
        return

    node = BNode()
    g.add((shape, SH["property"], node))
    g.add((node, SH["path"], EO[slot_name]))

    if getattr(slot, "required", False):
        g.add((node, SH["minCount"], Literal(1)))
    if not getattr(slot, "multivalued", False):
        g.add((node, SH["maxCount"], Literal(1)))

    range_name: Optional[str] = slot.range
    if range_name == "Entity":
        g.add((node, SH["nodeKind"], SH.IRI))
    elif range_name in sv.all_classes():
        g.add((node, SH["class"], EO[range_name]))
    elif range_name in getattr(sv.schema, "enums", {}):
        values = enum_values(range_name)
        if values:
            head = BNode()
            Collection(g, head, [Literal(v) for v in values])
            g.add((node, SH["in"], head))
    else:
        t = sv.schema.types.get(range_name)
        if t is not None:
            dt = _BUILTIN_DATATYPES.get(t.typeof)
            if dt is not None:
                g.add((node, SH["datatype"], dt))
            minimum = type_minimum(range_name)
            if minimum is not None:
                g.add((node, SH["minInclusive"], Literal(minimum)))
            maximum = getattr(t, "maximum_value", None)
            if maximum is not None:
                g.add((node, SH["maxInclusive"], Literal(maximum)))
        else:
            dt = _BUILTIN_DATATYPES.get(range_name)
            if dt is not None:
                g.add((node, SH["datatype"], dt))


def _emit_unique_shape(g: Graph, class_name: str, key_name: str, key_slots: List[str]) -> None:
    """模式 A：业务唯一键（复合键 = 同值全匹配；可选槽缺席自动跳过）。"""
    sv = schema_view()
    shape = EO[f"{class_name}{_camel(key_name)}UniqueShape"]
    g.add((shape, RDF.type, SH.NodeShape))
    g.add((shape, SH.targetClass, EO[class_name]))

    triples_this = " .\n                    ".join(f"$this eo:{s} ?v_{s}" for s in key_slots)
    triples_other = " .\n                    ".join(f"?other eo:{s} ?v_{s}" for s in key_slots)
    filters = " && ".join(f"bound(?v_{s})" for s in key_slots)
    select = (f"SELECT $this ?other WHERE {{\n"
              f"                    {triples_this} .\n"
              f"                    {triples_other} .\n"
              f"                    FILTER (?other != $this && {filters}) }}")
    _sparql_constraint(g, shape,
                       f"唯一键冲突（{key_name}）：{{$this}}",
                       select)


def _camel(s: str) -> str:
    return "".join(p.capitalize() for p in s.split("_"))


def build_l0_shapes() -> Graph:
    """每类 NodeShape（closed）+ 唯一键形状。"""
    sv = schema_view()
    g = Graph()
    g.bind("eo", EO)
    g.bind("sh", SH)

    for class_name in all_classes():
        if class_name == "Entity":
            continue
        shape = EO[f"{class_name}Shape"]
        g.add((shape, RDF.type, SH.NodeShape))
        g.add((shape, SH.targetClass, EO[class_name]))
        g.add((shape, SH.nodeKind, SH.IRI))
        g.add((shape, SH.closed, Literal(True)))
        ignored = BNode()
        Collection(g, ignored, [RDF.type])
        g.add((shape, SH.ignoredProperties, ignored))
        for slot_name in class_slots(class_name):
            _emit_property_shape(g, shape, class_name, slot_name)

        # unique_keys → SPARQL 唯一形状
        unique_keys = getattr(sv.get_class(class_name), "unique_keys", None) or {}
        for key_name, key in unique_keys.items():
            _emit_unique_shape(g, class_name, key_name, list(key.unique_key_slots))
    return g


# ---------------------------------------------------------------- L1 自动 ------
def build_l1_shapes() -> Graph:
    """模式 B：每个 Link 槽的引用完整性（悬空引用拦截）。"""
    sv = schema_view()
    g = Graph()
    g.bind("eo", EO)
    g.bind("sh", SH)

    for slot_name in sorted(sv.all_slots().keys()):
        slot = sv.get_slot(slot_name)
        if slot.range not in sv.all_classes():
            continue  # 只对 Link 槽
        shape = EO[f"{_camel(slot_name)}TargetExistsShape"]
        g.add((shape, RDF.type, SH.NodeShape))
        g.add((shape, SH.targetSubjectsOf, EO[slot_name]))
        _sparql_constraint(
            g, shape,
            f"悬空引用：{{$this}} 的 {slot_name} 指向数据集中不存在的实体",
            f"SELECT $this ?o WHERE {{ $this eo:{slot_name} ?o . "
            f"FILTER NOT EXISTS {{ ?o ?p ?v }} }}",
        )
    return g


def build_shapes_graph() -> Graph:
    """L0 + L1（自动部分）合并（手写 domain.ttl 由 validate.py 追加）。"""
    g = build_l0_shapes()
    for triple in build_l1_shapes():
        g.add(triple)
    return g


def save_shapes(path: str) -> None:
    build_shapes_graph().serialize(destination=path, format="turtle")
