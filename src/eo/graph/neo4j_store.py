# -*- coding: utf-8 -*-
"""Neo4j 图存储实现（官方 driver，惰性导入）。

生产环境用：节点 = (:Type {id, ...props})，边 = MERGE (a)-[:TYPE]->(b)。
本机无 Neo4j 服务器，故 demo 走 MemoryStore；有服务器后把工厂换成 Neo4jStore 即可，接口不变。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import Edge, GraphStore, Node


def _safe_label(label: str) -> str:
    """节点类型/关系类型包上反引号，防止 Cypher 关键字冲突。"""
    return "`" + label.replace("`", "") + "`"


class Neo4jStore(GraphStore):
    def __init__(self, uri: str = "bolt://localhost:7687",
                 user: str = "neo4j", password: str = "neo4j",
                 database: str = "neo4j") -> None:
        from neo4j import GraphDatabase  # 惰性导入，避免无服务器时也要求依赖

        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._db = database

    def _write(self, query: str, **params: Any) -> None:
        with self._driver.session(database=self._db) as session:
            session.run(query, **params)

    def _read(self, query: str, **params: Any) -> List[Any]:
        with self._driver.session(database=self._db) as session:
            return [record for record in session.run(query, **params)]

    # ---- 写入 ----
    def add_node(self, id: str, type: str, properties: Optional[Dict[str, Any]] = None) -> Node:
        """docs/02 §2.1 规范模式：MERGE :Entity 保证全局唯一 id，再 SET 类标签。"""
        props = dict(properties or {})
        self._write(
            f"MERGE (n:Entity {{id: $id}}) "
            f"SET n:{_safe_label(type)}, n.entity_type = $type, n += $props",
            id=id, type=type, props=props,
        )
        return Node(id, type, props)

    def add_edge(self, src: str, dst: str, type: str,
                 properties: Optional[Dict[str, Any]] = None) -> Edge:
        """docs/02 §3.2 规范模式：边类型 = UPPER_SNAKE_CASE(槽名)。"""
        props = dict(properties or {})
        rel = _safe_label(type.upper())
        self._write(
            f"MATCH (a:Entity {{id: $src}}) MATCH (b:Entity {{id: $dst}}) "
            f"MERGE (a)-[r:{rel}]->(b) SET r += $props",
            src=src, dst=dst, props=props,
        )
        return Edge(src, dst, type, props)

    # ---- 读取 ----
    def get_node(self, id: str) -> Optional[Node]:
        rows = self._read("MATCH (n {id: $id}) RETURN n, labels(n) AS l", id=id)
        if not rows:
            return None
        n, labels = rows[0]["n"], rows[0]["l"]
        props = dict(n)
        props.pop("id", None)
        node_type = labels[0] if labels else "Entity"
        return Node(id, node_type, props)

    def has_node(self, id: str) -> bool:
        return bool(self._read("MATCH (n {id: $id}) RETURN n LIMIT 1", id=id))

    def nodes(self) -> List[Node]:
        out = []
        for rec in self._read("MATCH (n) RETURN n, labels(n) AS l"):
            n, labels = rec["n"], rec["l"]
            props = dict(n)
            node_id = props.pop("id", None)
            out.append(Node(node_id, labels[0] if labels else "Entity", props))
        return out

    def edges(self, src: Optional[str] = None, dst: Optional[str] = None,
              type: Optional[str] = None) -> List[Edge]:
        query = "MATCH (a)-[r]->(b) WHERE true"
        params: Dict[str, Any] = {}
        if src is not None:
            query += " AND a.id = $src"; params["src"] = src
        if dst is not None:
            query += " AND b.id = $dst"; params["dst"] = dst
        if type is not None:
            query += f" AND type(r) = $type"; params["type"] = type
        query += " RETURN a.id AS s, b.id AS d, type(r) AS t, r"
        out = []
        for rec in self._read(query, **params):
            props = dict(rec["r"])
            out.append(Edge(rec["s"], rec["d"], rec["t"], props))
        return out

    def neighbors(self, id: str, type: Optional[str] = None,
                  direction: str = "out") -> List[Node]:
        rel = "-[r]->" if direction == "out" else "<-[r]-"
        query = f"MATCH (n {{id: $id}}){rel}(m) WHERE true"
        params: Dict[str, Any] = {"id": id}
        if type is not None:
            query += " AND type(r) = $type"; params["type"] = type
        query += " RETURN m, labels(m) AS l"
        out = []
        for rec in self._read(query, **params):
            m, labels = rec["m"], rec["l"]
            props = dict(m)
            node_id = props.pop("id", None)
            out.append(Node(node_id, labels[0] if labels else "Entity", props))
        return out

    def clear(self) -> None:
        self._write("MATCH (n) DETACH DELETE n")
