# -*- coding: utf-8 -*-
"""链路（Link）单元测试：建立/解除、单值覆盖、多值去重、引用完整性、路径查询。"""
from __future__ import annotations

import pytest

from eo.crud import CRUDError, ValidationError
from eo.graph.traversal import format_path, resolve, shortest_path, traverse
from eo.rules import part_of_robot, robot_of_part


class TestLinkCRUD:
    def test_link_and_get_links(self, crud):
        crud.link("eo:task/carry-cup", "eo:robot/ti5", "assigned_to")
        edges = crud.get_links("eo:task/carry-cup", "assigned_to")
        assert any(e["dst"] == "eo:robot/ti5" for e in edges)

    def test_link_replaces_single_value(self, crud):
        crud.link("eo:task/carry-cup", "eo:robot/bx2", "assigned_to")
        assert crud.get("eo:task/carry-cup")["assigned_to"] == "eo:robot/bx2"

    def test_link_multivalue_dedup(self, crud):
        # requires_capability 已含 power-grasp，重复 link 不产生重复边
        crud.link("eo:task/carry-cup", "eo:cap/power-grasp", "requires_capability")
        caps = crud.get("eo:task/carry-cup")["requires_capability"]
        assert caps.count("eo:cap/power-grasp") == 1

    def test_unlink(self, crud):
        crud.link("eo:task/carry-cup", "eo:robot/bx2", "assigned_to")
        crud.unlink("eo:task/carry-cup", "eo:robot/bx2", "assigned_to")
        assert crud.get("eo:task/carry-cup").get("assigned_to") is None

    def test_link_rejects_dangling_target(self, crud):
        with pytest.raises(CRUDError):
            crud.link("eo:robot/ti5", "eo:part/ghost", "has_part")

    def test_link_rejects_non_link_slot(self, crud):
        with pytest.raises(CRUDError):
            crud.link("eo:object/cup", "eo:robot/ti5", "weight_kg")


class TestLinkIntegrity:
    def test_physical_delete_referenced_rejected(self, crud):
        """被引用的实体物理删除 → Gate A 悬空引用拒绝。"""
        with pytest.raises(ValidationError) as exc:
            crud.delete("eo:cap/power-grasp", physical=True)
        assert exc.value.report.violations
        assert crud.get("eo:cap/power-grasp") is not None, "拒绝后回滚"

    def test_physical_delete_unreferenced(self, crud):
        """无入边引用的实体（测点定义）可物理删除。"""
        crud.delete("eo:metric/joint-angle", physical=True)
        assert crud.get("eo:metric/joint-angle") is None
        assert crud.validate().conforms

    def test_unlink_removes_edge(self, crud):
        n_before = len(crud.get_links("eo:task/carry-cup"))
        crud.unlink("eo:task/carry-cup", "eo:robot/ti5", "assigned_to")
        assert len(crud.get_links("eo:task/carry-cup")) == n_before - 1


class TestPathQueries:
    def test_traverse_part_tree(self, store):
        # part_of 边方向「子→父」：上溯父链走 out
        up = traverse(store, "eo:part/ti5/six-axis-force", {"part_of"}, "out")
        assert {"eo:part/ti5/wrist", "eo:part/ti5/arm"} <= up

    def test_shortest_path(self, store):
        path = shortest_path(store, "eo:robot/ti5", "eo:cap/pour")
        assert path is not None and len(path) == 2
        assert "HAS_PART" in format_path(path) and "PROVIDES_CAPABILITY" in format_path(path)

    def test_resolve_dependency_chain(self, store):
        parts = resolve(store, "eo:task/grasp-egg",
                        [("out", "requires_capability"), ("in", "provides_capability")])
        assert {"eo:part/ti5/dexterous-hand", "eo:part/ti5/six-axis-force"} <= set(parts)

    def test_part_of_robot(self, store):
        assert part_of_robot(store, "eo:part/ti5/six-axis-force", "eo:robot/ti5")
        assert not part_of_robot(store, "eo:part/ti5/arm", "eo:robot/bx2")
        assert robot_of_part(store, "eo:part/ti5/arm") == "eo:robot/ti5"
        # 根部件本身
        assert part_of_robot(store, "eo:part/bx2/head", "eo:robot/bx2")
