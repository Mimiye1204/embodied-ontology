# -*- coding: utf-8 -*-
"""对象（Object）+ 属性（Property）单元测试：CRUD、Gate A 校验、回滚、不可变字段。"""
from __future__ import annotations

import pytest

from eo.crud import CRUDError, ValidationError

PEN = {"id": "eo:object/pen", "type": "Object", "label": "笔",
       "weight_kg": 0.02, "surface": "dry", "created_at": "2026-11-24T10:00:00+08:00"}


class TestObjectCreate:
    def test_create_valid(self, crud):
        crud.create(dict(PEN))
        assert crud.get("eo:object/pen")["label"] == "笔"
        assert crud.validate().conforms

    def test_create_rejects_duplicate_id(self, crud):
        crud.create(dict(PEN))
        with pytest.raises(CRUDError):
            crud.create(dict(PEN))

    def test_create_rejects_unknown_type(self, crud):
        with pytest.raises(CRUDError):
            crud.create({"id": "eo:x", "type": "Nope", "label": "x"})

    def test_create_rejects_missing_required(self, crud):
        # Task 必须 requires_capability ≥1；label/created_at 必填
        with pytest.raises(ValidationError):
            crud.create({"id": "eo:task/bad", "type": "Task", "label": "坏任务"})


class TestObjectReadList:
    def test_get_returns_copy(self, crud):
        ent = crud.get("eo:robot/ti5")
        assert ent["serial"] == "TI5-T170C-001"
        ent["serial"] = "mutated"
        assert crud.get("eo:robot/ti5")["serial"] == "TI5-T170C-001"

    def test_list_filter(self, crud):
        tasks = crud.list(type="Task")
        assert all(t["type"] == "Task" for t in tasks)
        pending = crud.list(type="Task", where={"status": "pending"})
        assert all(t["status"] == "pending" for t in pending)
        assert len(pending) <= len(tasks)


class TestProperty:
    def test_set_get_unset(self, crud):
        crud.set_property("eo:object/cup", "weight_kg", 0.35)
        assert crud.get_property("eo:object/cup", "weight_kg") == 0.35
        crud.unset_property("eo:object/cup", "weight_kg")
        assert crud.get_property("eo:object/cup", "weight_kg") is None
        assert crud.validate().conforms

    def test_bad_value_rejected_and_rolls_back(self, crud):
        before = crud.get("eo:object/cup")["surface"]
        with pytest.raises(ValidationError) as exc:
            crud.set_property("eo:object/cup", "surface", "wet")
        assert exc.value.report.violations, "应携带结构化违规报告"
        assert crud.get("eo:object/cup")["surface"] == before, "拒绝后状态应回滚"

    def test_set_on_link_slot_rejected(self, crud):
        with pytest.raises(CRUDError):
            crud.set_property("eo:task/carry-cup", "assigned_to", "eo:robot/ti5")

    def test_unset_required_slot_rejected(self, crud):
        with pytest.raises(CRUDError):
            crud.unset_property("eo:robot/ti5", "label")


class TestObjectUpdateDelete:
    def test_update_immutable_fields(self, crud):
        with pytest.raises(CRUDError):
            crud.update("eo:object/cup", {"type": "Robot"})
        with pytest.raises(CRUDError):
            crud.update("eo:object/cup", {"id": "eo:x"})

    def test_soft_delete(self, crud):
        crud.create(dict(PEN))
        crud.delete("eo:object/pen")
        assert crud.get("eo:object/pen")["deprecated"] is True
        assert all(e["id"] != "eo:object/pen" for e in crud.list())

    def test_physical_delete(self, crud):
        crud.create(dict(PEN))
        crud.delete("eo:object/pen", physical=True)
        assert crud.get("eo:object/pen") is None
