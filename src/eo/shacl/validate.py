# -*- coding: utf-8 -*-
"""SHACL 实例校验执行（docs/03 §6 校验门 A/C 的执行器）。

形状图 = L0（Schema 自动生成）+ L1 自动（引用完整性）+ L1 手写（domain.ttl）。
数据图 = JSON-LD 文档经 rdflib 解析（同一份数据既是交换格式也是校验输入）。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from ..jsonld.exchange import to_jsonld_document, to_rdf_graph
from .shapes import build_shapes_graph

_DOMAIN_TTL = os.path.join(os.path.dirname(__file__), "domain.ttl")

_shapes = None


def shapes_graph():
    """L0 + L1（自动 + 手写）合并后的形状图（缓存）。"""
    global _shapes
    if _shapes is None:
        _shapes = build_shapes_graph()
        _shapes.parse(_DOMAIN_TTL, format="turtle")
    return _shapes


def validate_entities(entities: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """校验实体列表；返回 (是否符合, 人类可读报告)。"""
    from pyshacl import validate

    doc = to_jsonld_document(entities)
    data = to_rdf_graph(doc)
    conforms, _, report_text = validate(
        data_graph=data,
        shacl_graph=shapes_graph(),
        inference="none",
    )
    return bool(conforms), str(report_text)
