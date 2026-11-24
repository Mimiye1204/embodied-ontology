# -*- coding: utf-8 -*-
"""具身本体论引擎（Embodied Ontology Engine）。

分层：
  schema/embodied_ontology.yaml  结构层（LinkML TBox，单一事实来源）
  eo.jsonld                      交换层（JSON-LD 全域交换格式）
  eo.graph                       存储层（Neo4j / 内存图，统一 GraphStore 接口）
  eo.rules                       计算层（自研轻量规则引擎：故障传播/动作拦截/任务可达性）
  eo.shacl                       校验层（SHACL 实例校验）
  eo.timeseries                  时序层（TimescaleDB / SQLite，外键关联本体实体）
"""

__version__ = "0.1.0"
