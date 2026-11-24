# -*- coding: utf-8 -*-
"""SHACL 实例校验执行（docs/03 §6 校验门 A/C 的执行器 + §8 结构化报告落地）。

形状图 = L0（Schema 自动生成）+ L1 自动（引用完整性）+ L1 手写（domain.ttl）。
数据图 = JSON-LD 文档经 rdflib 解析（同一份数据既是交换格式也是校验输入）。

结构化报告（validate_entities_structured）：
  pyshacl 的 results_graph（RDF）→ Violation 列表（focus_node/path/message/severity/source_shape），
  平台侧可逐条跳转实体。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from rdflib import RDF, Namespace

from ..jsonld.exchange import compact_iri, to_jsonld_document, to_rdf_graph
from .shapes import build_shapes_graph

_DOMAIN_TTL = os.path.join(os.path.dirname(__file__), "domain.ttl")
_SH = Namespace("http://www.w3.org/ns/shacl#")

_shapes = None


def shapes_graph():
    """L0 + L1（自动 + 手写）合并后的形状图（缓存）。"""
    global _shapes
    if _shapes is None:
        _shapes = build_shapes_graph()
        _shapes.parse(_DOMAIN_TTL, format="turtle")
    return _shapes


# ---------------------------------------------------------------- 结构化报告
@dataclass
class Violation:
    focus_node: str
    message: str
    path: Optional[str] = None
    severity: str = "Violation"      # Violation / Warning / Info
    source_shape: Optional[str] = None


@dataclass
class ValidationReport:
    conforms: bool
    violations: List[Violation] = field(default_factory=list)
    warnings: List[Violation] = field(default_factory=list)

    def __str__(self) -> str:
        if self.conforms:
            return "SHACL 校验：通过 ✓"
        lines = [f"SHACL 校验：失败 ✗（{len(self.violations)} 项违规"
                 + (f"，{len(self.warnings)} 项警告" if self.warnings else "") + "）"]
        for v in self.violations:
            loc = v.focus_node + (f" .{v.path}" if v.path else "")
            lines.append(f"  ✗ {loc}\n      {v.message}" + (f"  [{v.source_shape}]" if v.source_shape else ""))
        for v in self.warnings:
            lines.append(f"  ⚠ {v.focus_node} {v.message}")
        return "\n".join(lines)


def _parse_report(conforms: bool, results_graph) -> ValidationReport:
    report = ValidationReport(conforms=bool(conforms))
    for r in results_graph.subjects(RDF.type, _SH.ValidationResult):
        sev_term = results_graph.value(r, _SH.resultSeverity) or _SH.Violation
        severity = str(sev_term).rsplit("#", 1)[-1]
        path_term = results_graph.value(r, _SH.resultPath)
        shape_term = results_graph.value(r, _SH.sourceShape)
        v = Violation(
            focus_node=compact_iri(str(results_graph.value(r, _SH.focusNode))),
            message=str(results_graph.value(r, _SH.resultMessage) or ""),
            path=compact_iri(str(path_term)) if path_term else None,
            severity=severity,
            source_shape=compact_iri(str(shape_term)) if shape_term else None,
        )
        if severity == "Violation":
            report.violations.append(v)
        else:
            report.warnings.append(v)
    return report


def validate_entities_structured(entities: List[Dict[str, Any]]) -> ValidationReport:
    """校验实体列表；返回结构化报告（框架文档 §8）。"""
    from pyshacl import validate

    doc = to_jsonld_document(entities)
    data = to_rdf_graph(doc)
    conforms, results_graph, _ = validate(
        data_graph=data,
        shacl_graph=shapes_graph(),
        inference="none",
    )
    return _parse_report(conforms, results_graph)


def validate_entities(entities: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """校验实体列表；返回 (是否符合, 人类可读报告)。（旧接口，结构化请用上面那个）"""
    report = validate_entities_structured(entities)
    return report.conforms, str(report)
