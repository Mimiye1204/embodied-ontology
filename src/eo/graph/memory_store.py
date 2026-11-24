# -*- coding: utf-8 -*-
"""纯 Python 内存图实现（零外部依赖），作为无 Neo4j 服务器时的回退存储。

用于本地跑通全链路 demo；接口与 Neo4jStore 完全一致。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import Edge, GraphStore, Node


class MemoryStore(GraphStore):
    def __init__(self) -> None:
        self._nodes: Dict[str, Node] = {}
        self._edges: List[Edge] = []

    # ---- 写入 ----
    def add_node(self, id: str, type: str, properties: Optional[Dict[str, Any]] = None) -> Node:
        node = Node(id, type, dict(properties or {}))
        self._nodes[id] = node
        return node

    def add_edge(self, src: str, dst: str, type: str,
                 properties: Optional[Dict[str, Any]] = None) -> Edge:
        edge = Edge(src, dst, type, dict(properties or {}))
        self._edges.append(edge)
        return edge

    # ---- 读取 ----
    def get_node(self, id: str) -> Optional[Node]:
        return self._nodes.get(id)

    def has_node(self, id: str) -> bool:
        return id in self._nodes

    def nodes(self) -> List[Node]:
        return list(self._nodes.values())

    def edges(self, src: Optional[str] = None, dst: Optional[str] = None,
              type: Optional[str] = None) -> List[Edge]:
        out = []
        for e in self._edges:
            if src is not None and e.src != src:
                continue
            if dst is not None and e.dst != dst:
                continue
            if type is not None and e.type != type:
                continue
            out.append(e)
        return out

    def neighbors(self, id: str, type: Optional[str] = None,
                  direction: str = "out") -> List[Node]:
        result: List[Node] = []
        for e in self._edges:
            if direction == "out" and e.src == id:
                target = e.dst
            elif direction == "in" and e.dst == id:
                target = e.src
            else:
                continue
            if type is not None and e.type != type:
                continue
            node = self._nodes.get(target)
            if node is not None:
                result.append(node)
        return result

    def clear(self) -> None:
        self._nodes.clear()
        self._edges.clear()
