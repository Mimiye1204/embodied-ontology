# -*- coding: utf-8 -*-
"""GraphStore 接口：本体实体对象库（ABox）的存储抽象。

Node = 实体（ObjectType 实例），Edge = Link（ObjectType 之间的有向关系）。
Neo4j 与内存实现共用同一接口；规则引擎、JSON-LD、时序层都只依赖本接口。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Node:
    id: str
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.properties.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.properties[key]


@dataclass
class Edge:
    src: str
    dst: str
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)


class GraphStore(ABC):
    """本体图的统一访问接口。"""

    # ---- 写入 ----
    @abstractmethod
    def add_node(self, id: str, type: str, properties: Optional[Dict[str, Any]] = None) -> Node: ...

    @abstractmethod
    def add_edge(self, src: str, dst: str, type: str,
                 properties: Optional[Dict[str, Any]] = None) -> Edge: ...

    # ---- 读取 ----
    @abstractmethod
    def get_node(self, id: str) -> Optional[Node]: ...

    @abstractmethod
    def has_node(self, id: str) -> bool: ...

    @abstractmethod
    def nodes(self) -> List[Node]: ...

    @abstractmethod
    def edges(self, src: Optional[str] = None, dst: Optional[str] = None,
              type: Optional[str] = None) -> List[Edge]: ...

    @abstractmethod
    def neighbors(self, id: str, type: Optional[str] = None,
                  direction: str = "out") -> List[Node]: ...

    @abstractmethod
    def clear(self) -> None: ...

    # ---- 便捷遍历 ----
    def out_neighbors(self, id: str, type: Optional[str] = None) -> List[Node]:
        return self.neighbors(id, type, "out")

    def in_neighbors(self, id: str, type: Optional[str] = None) -> List[Node]:
        return self.neighbors(id, type, "in")
