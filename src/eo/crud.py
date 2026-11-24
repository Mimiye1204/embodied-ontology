# -*- coding: utf-8 -*-
"""本体 ABox CRUD（docs/03 校验门 A 的落地层）：Object / Property / Link 基础操作。

语义：
- 写操作 = 补丁浅合并 → 全量 SHACL 校验（Gate A）→ 原子提交；
  校验失败抛 ValidationError（含结构化报告），状态不变（回滚语义）。
- Object = 实体实例；Property = 实体上的标量属性；Link = 实体间的有向关系。
- id 不可变、type 不可变更；删除策划类实体用软删除（deprecated），
  物理删除若留下悬空引用会被 Gate A 拒绝（先解除依赖再删）。
- 读操作返回 JSON-LD 视图（与导出格式同构，可直接交换）。
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from .graph import GraphStore, MemoryStore
from .graph.loader import load_entities
from .jsonld.exchange import export_jsonld
from .schema import concrete_classes, link_slots, scalar_slots
from .shacl import validate_entities_structured
from .shacl.validate import ValidationReport


class CRUDError(Exception):
    """CRUD 语义错误（未知类型 / 非法槽 / 重复 id / 目标不存在等，非校验违规）。"""


class ValidationError(Exception):
    """Gate A 校验失败：写操作被拒绝，状态未改变。"""

    def __init__(self, report: ValidationReport) -> None:
        super().__init__(f"SHACL 校验失败（{len(report.violations)} 项违规）")
        self.report = report


class OntologyCRUD:
    """本体实体对象库的 CRUD 服务（唯一写路径）。"""

    def __init__(self, store: Optional[GraphStore] = None) -> None:
        self.store: GraphStore = store or MemoryStore()
        self.entities: Dict[str, Dict[str, Any]] = {}   # id → 实体 dict（权威状态）

    # ================================================================ 装载
    def load(self, entities: List[Dict[str, Any]]) -> None:
        """装载初始世界（Gate A 校验，失败抛 ValidationError）。"""
        merged = {e["id"]: dict(e) for e in entities}
        report = validate_entities_structured(list(merged.values()))
        if not report.conforms:
            raise ValidationError(report)
        self.entities = merged
        self._rebuild()

    def _rebuild(self) -> None:
        self.store.clear()
        load_entities(self.store, list(self.entities.values()))

    def _commit(self, new_state: Dict[str, Dict[str, Any]], action: str) -> None:
        report = validate_entities_structured(list(new_state.values()))
        if not report.conforms:
            raise ValidationError(report)
        self.entities = new_state
        self._rebuild()

    # ================================================================ Object
    def create(self, entity: Dict[str, Any]) -> None:
        """新建实体（Object）。id 重复 → CRUDError。"""
        eid = entity.get("id")
        if not eid:
            raise CRUDError("实体缺少 id")
        if eid in self.entities:
            raise CRUDError(f"实体 {eid} 已存在（更新请用 update）")
        if entity.get("type") not in concrete_classes():
            raise CRUDError(f"未知 ObjectType '{entity.get('type')}'（LinkML Schema 未定义）")
        self.apply([entity], action="create")

    def get(self, id: str) -> Optional[Dict[str, Any]]:
        """读实体（JSON-LD 视图深拷贝）。"""
        return copy.deepcopy(self.entities.get(id))

    def list(self, type: Optional[str] = None,
             where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """列出实体（默认过滤已废弃）。where = 属性等值匹配。"""
        out = [copy.deepcopy(e) for e in self.entities.values()
               if not e.get("deprecated")]
        if type:
            out = [e for e in out if e["type"] == type]
        if where:
            out = [e for e in out if all(e.get(k) == v for k, v in where.items())]
        return out

    def update(self, id: str, patch: Dict[str, Any]) -> None:
        """更新实体（补丁浅合并；None=保留现值；id/type 不可变）。"""
        if id not in self.entities:
            raise CRUDError(f"实体 {id} 不存在")
        if "id" in patch and patch["id"] != id:
            raise CRUDError("id 不可变更")
        self.apply([{"id": id, **patch}], action="update")

    def delete(self, id: str, physical: bool = False) -> None:
        """删除实体。

        - 软删除（默认）：置 deprecated=true（策划类实体规范，docs/02 §5）
        - 物理删除：移除节点与出边；若其他实体仍引用它（悬空引用），Gate A 拒绝，
          需先 unlink 解除依赖
        """
        if id not in self.entities:
            raise CRUDError(f"实体 {id} 不存在")
        if not physical:
            self.apply([{"id": id, "deprecated": True}], action="soft-delete")
            return
        new_state = {k: dict(v) for k, v in self.entities.items() if k != id}
        self._commit(new_state, "physical-delete")

    # ================================================================ Property
    def get_property(self, id: str, slot: str) -> Any:
        ent = self.entities.get(id)
        if ent is None:
            raise CRUDError(f"实体 {id} 不存在")
        return copy.deepcopy(ent.get(slot))

    def set_property(self, id: str, slot: str, value: Any) -> None:
        """设置标量属性（Link 槽请用 link()）。"""
        ent = self.entities.get(id)
        if ent is None:
            raise CRUDError(f"实体 {id} 不存在")
        if slot in link_slots(ent["type"]):
            raise CRUDError(f"'{slot}' 是 Link 槽，请用 link() 操作")
        self.update(id, {slot: value})

    def unset_property(self, id: str, slot: str) -> None:
        """移除属性（Key 级删除）。"""
        ent = self.entities.get(id)
        if ent is None:
            raise CRUDError(f"实体 {id} 不存在")
        if slot in ("id", "label", "created_at"):
            raise CRUDError(f"必填槽 '{slot}' 不可移除")
        new_state = {k: dict(v) for k, v in self.entities.items()}
        new_state[id].pop(slot, None)
        self._commit(new_state, "unset-property")

    # ================================================================ Link
    def link(self, src: str, dst: str, type: str) -> None:
        """建立有向关系（Link）。单值槽覆盖旧值；多值槽去重追加。"""
        src_ent = self.entities.get(src)
        if src_ent is None:
            raise CRUDError(f"实体 {src} 不存在")
        valid = link_slots(src_ent["type"])
        if type not in valid:
            raise CRUDError(f"{src_ent['type']} 没有 Link 槽 '{type}'；可用：{valid}")
        if dst not in self.entities:
            raise CRUDError(f"目标实体 {dst} 不存在")
        cur = src_ent.get(type)
        if isinstance(cur, list):
            new_val = cur if dst in cur else cur + [dst]
        else:
            new_val = dst
        self.apply([{"id": src, type: new_val}], action="link")

    def unlink(self, src: str, dst: Optional[str] = None, type: Optional[str] = None) -> None:
        """移除关系。type=None 时移除 src 的全部出边。"""
        src_ent = self.entities.get(src)
        if src_ent is None:
            raise CRUDError(f"实体 {src} 不存在")
        new_state = {k: dict(v) for k, v in self.entities.items()}
        ent = new_state[src]
        if type is None:
            for slot in link_slots(ent["type"]):
                ent.pop(slot, None)
        else:
            if type not in link_slots(ent["type"]):
                raise CRUDError(f"{ent['type']} 没有 Link 槽 '{type}'")
            cur = ent.get(type)
            if isinstance(cur, list):
                rest = [x for x in cur if x != dst] if dst is not None else []
                if rest:
                    ent[type] = rest
                else:
                    ent.pop(type, None)
            elif cur is not None:
                ent.pop(type, None)
        self._commit(new_state, "unlink")

    def get_links(self, id: str, type: Optional[str] = None,
                  direction: str = "out") -> List[Dict[str, str]]:
        """读实体关系：返回 [{src, dst, type}, ...]。"""
        edges = self.store.edges(src=id if direction == "out" else None,
                                 dst=id if direction == "in" else None,
                                 type=type)
        return [{"src": e.src, "dst": e.dst, "type": e.type} for e in edges]

    # ================================================================ 批量写
    def apply(self, updates: List[Dict[str, Any]], action: str = "batch") -> None:
        """批量补丁：浅合并（None=保留现值）→ Gate A 全量校验 → 原子提交。

        一个批次整体校验：要么全部落地，要么全部拒绝。
        """
        new_state = {k: dict(v) for k, v in self.entities.items()}
        for u in updates:
            eid = u.get("id")
            if not eid:
                raise CRUDError("补丁缺少 id")
            if eid in new_state:
                if u.get("type") and u["type"] != new_state[eid].get("type"):
                    raise CRUDError(f"实体 {eid} 类型不可变更")
                patch = {k: v for k, v in u.items() if v is not None}
                new_state[eid] = {**new_state[eid], **patch}
            else:
                if u.get("type") not in concrete_classes():
                    raise CRUDError(f"未知 ObjectType '{u.get('type')}'")
                new_state[eid] = dict(u)
        self._commit(new_state, action)

    # ================================================================ 校验/导出
    def validate(self) -> ValidationReport:
        """Gate C/D：当前全量状态的校验。"""
        return validate_entities_structured(list(self.entities.values()))

    def export_jsonld(self, path: Optional[str] = None) -> Dict[str, Any]:
        """导出当前状态为 JSON-LD 文档。"""
        return export_jsonld(self.store, path)
