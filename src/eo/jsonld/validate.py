# -*- coding: utf-8 -*-
"""JSON-LD 输出校验：保证导出可被任何消费者（含仿真）读回并重建等价本体。

校验链路：
  结构完整（@context/@graph）→ 可解析为 RDF → round-trip 重导入
  → 重导入实体经 SHACL 合法（Gate A/C）→ 与原始 id 集一致（无损）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..graph.base import GraphStore
from ..shacl.validate import ValidationReport, Violation, validate_entities_structured
from .exchange import export_jsonld, from_jsonld_document, to_rdf_graph


def validate_jsonld_document(doc: Dict[str, Any]) -> ValidationReport:
    """校验一个独立的 JSON-LD 文档（结构 + RDF 可解析 + 重导入实体 SHACL）。"""
    violations: List[Violation] = []

    if not doc.get("@context"):
        violations.append(Violation("@document", "缺 @context"))
    graph = doc.get("@graph")
    if not isinstance(graph, list):
        violations.append(Violation("@document", "@graph 缺失或非列表"))
    if violations:
        return ValidationReport(conforms=False, violations=violations)

    try:
        to_rdf_graph(doc)
    except Exception as e:  # noqa: BLE001
        violations.append(Violation("@document", f"无法解析为 RDF：{e}"))
        return ValidationReport(conforms=False, violations=violations)

    try:
        entities = from_jsonld_document(doc)
    except Exception as e:  # noqa: BLE001
        violations.append(Violation("@document", f"round-trip 重导入失败：{e}"))
        return ValidationReport(conforms=False, violations=violations)

    return validate_entities_structured(entities)


def validate_jsonld(store: GraphStore, types: Optional[List[str]] = None,
                    ids: Optional[List[str]] = None) -> ValidationReport:
    """从图导出 JSON-LD 并校验（结构 + round-trip 无损 + 重导入 SHACL）。

    返回 ValidationReport：conforms=False 时 violations 含结构/无损/SHACL 三类问题。
    """
    doc = export_jsonld(store, types=types, ids=ids)
    report = validate_jsonld_document(doc)
    if not report.conforms:
        return report

    # round-trip 无损：导出 @graph 与重导入实体的 id 集一致
    exported_ids = {e["id"] for e in doc["@graph"]}
    back = from_jsonld_document(doc)
    back_ids = {e["id"] for e in back}
    if exported_ids != back_ids:
        missing = exported_ids - back_ids
        extra = back_ids - exported_ids
        report.violations.append(Violation(
            "@document",
            f"round-trip 无损校验失败：缺失 {len(missing)} 个，多出 {len(extra)} 个"))
        report.conforms = False
    return report
