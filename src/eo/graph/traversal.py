# -*- coding: utf-8 -*-
"""基础图路径查询封装（「图推理 = 遍历」的基础件，docs/04 §5）。

在 GraphStore 之上提供可复用的图遍历原语，规则层（可达性/故障传播/绑定）
复用这一层，不再各自手写 BFS：

- traverse / descendants / ancestors   —— 有向可达集（BFS，支持边类型过滤/深度上限）
- reachable / shortest_path / all_paths —— 可达性判定与路径查找
- resolve —— 异构路径解析：按「(方向, 边类型)」步骤序列展开（任务→能力←部件）
- format_path —— 路径人类可读化（A -TYPE-> B <-TYPE- C）

约定：edge_types 为 None 表示任意边；为集合/列表时只沿这些边类型。
"""
from __future__ import annotations

from typing import List, Optional, Set, Union

from .base import Edge, GraphStore

EdgeTypes = Optional[Union[Set[str], List[str]]]
Step = tuple  # (direction, edge_type)


def _norm(edge_types: EdgeTypes) -> Optional[Set[str]]:
    return set(edge_types) if edge_types is not None else None


def _edges_from(store: GraphStore, node: str, edge_types: EdgeTypes, direction: str):
    """从 node 出发（out/in）的 (Edge, 对端 id) 序列，按边类型过滤。"""
    allowed = _norm(edge_types)
    if direction == "out":
        for e in store.edges(src=node):
            if allowed is None or e.type in allowed:
                yield e, e.dst
    else:
        for e in store.edges(dst=node):
            if allowed is None or e.type in allowed:
                yield e, e.src


def neighbors(store: GraphStore, node: str, edge_types: EdgeTypes = None,
              direction: str = "out") -> List[str]:
    """单跳邻居 id 列表。"""
    return [dst for _, dst in _edges_from(store, node, edge_types, direction)]


def traverse(store: GraphStore, start: str, edge_types: EdgeTypes = None,
             direction: str = "out", max_depth: Optional[int] = None) -> Set[str]:
    """BFS 可达集（不含起点）。"""
    seen: Set[str] = {start}
    frontier: List[str] = [start]
    depth = 0
    while frontier:
        if max_depth is not None and depth >= max_depth:
            break
        nxt: List[str] = []
        for node in frontier:
            for _, dst in _edges_from(store, node, edge_types, direction):
                if dst not in seen:
                    seen.add(dst)
                    nxt.append(dst)
        frontier = nxt
        depth += 1
    seen.discard(start)
    return seen


def descendants(store: GraphStore, node: str, edge_types: EdgeTypes = None,
                max_depth: Optional[int] = None) -> Set[str]:
    return traverse(store, node, edge_types, "out", max_depth)


def ancestors(store: GraphStore, node: str, edge_types: EdgeTypes = None,
              max_depth: Optional[int] = None) -> Set[str]:
    return traverse(store, node, edge_types, "in", max_depth)


def reachable(store: GraphStore, src: str, dst: str, edge_types: EdgeTypes = None,
              direction: str = "out", max_depth: Optional[int] = None) -> bool:
    return dst in traverse(store, src, edge_types, direction, max_depth)


def shortest_path(store: GraphStore, src: str, dst: str,
                  edge_types: EdgeTypes = None, direction: str = "out",
                  max_depth: Optional[int] = None) -> Optional[List[Edge]]:
    """最短路径，返回边序列（含方向信息）；不可达 → None。"""
    if src == dst:
        return []
    prev: dict = {src: None}  # node -> (edge, prev_node)
    frontier = [src]
    depth = 0
    while frontier:
        if max_depth is not None and depth >= max_depth:
            break
        nxt = []
        for node in frontier:
            for e, to in _edges_from(store, node, edge_types, direction):
                if to in prev:
                    continue
                prev[to] = (e, node)
                if to == dst:
                    return _reconstruct(prev, dst)
                nxt.append(to)
        frontier = nxt
        depth += 1
    return None


def _reconstruct(prev: dict, dst: str) -> List[Edge]:
    edges: List[Edge] = []
    cur = dst
    while prev[cur] is not None:
        e, before = prev[cur]
        edges.append(e)
        cur = before
    return list(reversed(edges))


def all_paths(store: GraphStore, src: str, dst: str,
              edge_types: EdgeTypes = None, direction: str = "out",
              max_depth: int = 8, limit: int = 100) -> List[List[Edge]]:
    """简单路径（不重复节点）枚举，上限 limit 条。"""
    allowed = _norm(edge_types)
    out: List[List[Edge]] = []

    def dfs(node: str, visited: set, path: List[Edge]):
        if len(out) >= limit:
            return
        if node == dst:
            out.append(list(path))
            return
        if len(path) >= max_depth:
            return
        for e, to in _edges_from(store, node, allowed, direction):
            if to in visited:
                continue
            visited.add(to)
            path.append(e)
            dfs(to, visited, path)
            path.pop()
            visited.remove(to)

    dfs(src, {src}, [])
    return out


def resolve(store: GraphStore, start: str, steps: List[Step]) -> List[str]:
    """异构路径解析：按步骤序列展开，返回终点节点 id 列表。

    steps 每项为 (direction, edge_type)，例如任务依赖部件：
      resolve(store, task_id, [("out", "requires_capability"),
                               ("in", "provides_capability")])
    """
    frontier: Set[str] = {start}
    for direction, edge_type in steps:
        nxt: Set[str] = set()
        for node in frontier:
            for _, to in _edges_from(store, node, {edge_type}, direction):
                nxt.add(to)
        frontier = nxt
        if not frontier:
            break
    return sorted(frontier)


def format_path(edges: List[Edge]) -> str:
    """边序列 → 人类可读路径（A -TYPE-> B <-TYPE- C）。"""
    if not edges:
        return "(空路径)"
    parts = [edges[0].src]
    for e in edges:
        if e.src == parts[-1]:
            parts.append(f"-{e.type.upper()}->")
        else:
            parts.append(f"<-{e.type.upper()}-")
        parts.append(e.dst)
    return " ".join(parts)
