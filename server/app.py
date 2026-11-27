# -*- coding: utf-8 -*-
"""本体引擎 REST API（本地草稿 · 未入仓库）。

对齐 robot-dispatch-server 风格：/internal/* 走 X-Internal-Token 鉴权
（常量时间比对，未配置/不匹配返回 503，照抄平台的 telemetry.go 模式）。
端点对应 docs/06 §6。

运行：
  .venv/Scripts/python.exe -m uvicorn server.app:app --host 0.0.0.0 --port 8091
  （令牌：环境变量 ONTOLOGY_INTERNAL_TOKEN，默认 test-ontology-token）
"""
import json
import os
import secrets
import sqlite3
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from eo.actions import build_registry
from eo.crud import CRUDError, OntologyCRUD, ValidationError
from eo.timeseries.base import TelemetryStore, now_iso
from eo.timeseries.binding import BindingRegistry
from eo.views import build_capability_view

INTERNAL_TOKEN = os.environ.get("ONTOLOGY_INTERNAL_TOKEN", "test-ontology-token")

app = FastAPI(title="具身本体论引擎 API", version="1.0.0")


class ThreadSafeTelemetry(TelemetryStore):
    """Web 多线程下的遥测存储：sqlite check_same_thread=False + 锁（草稿，仅 server 内）。"""

    def __init__(self, path: str = ":memory:"):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS telemetry ("
                           "time TEXT, entity_ref TEXT, metric TEXT, value REAL)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tel ON telemetry(entity_ref, time)")

    def insert(self, entity_ref, metric, value, time=None):
        with self._lock:
            self._conn.execute("INSERT INTO telemetry VALUES (?,?,?,?)",
                               (time or now_iso(), entity_ref, metric, float(value)))
            self._conn.commit()

    def query(self, entity_ref=None, metric=None, start=None, end=None):
        with self._lock:
            sql = "SELECT entity_ref, metric, value, time FROM telemetry WHERE 1=1"
            args = []
            if entity_ref:
                sql += " AND entity_ref=?"; args.append(entity_ref)
            if metric:
                sql += " AND metric=?"; args.append(metric)
            rows = self._conn.execute(sql + " ORDER BY time", args).fetchall()
            from eo.timeseries.base import TelemetryRow
            return [TelemetryRow(r[0], r[1], r[2], r[3]) for r in rows]

    def last(self, entity_ref, metric):
        with self._lock:
            rows = self._conn.execute(
                "SELECT entity_ref, metric, value, time FROM telemetry "
                "WHERE entity_ref=? AND metric=? ORDER BY time DESC LIMIT 1",
                (entity_ref, metric)).fetchall()
            if not rows:
                return None
            from eo.timeseries.base import TelemetryRow
            r = rows[0]
            return TelemetryRow(r[0], r[1], r[2], r[3])

    def close(self):
        self._conn.close()


# ---- 装载本体世界（草稿：从 fleet.json 内存装载；生产应接持久化存储）----
crud = OntologyCRUD()
with open(ROOT / "examples" / "fleet.json", encoding="utf-8") as f:
    crud.load(json.load(f))
registry = build_registry(crud)
telemetry = ThreadSafeTelemetry(":memory:")
bindings = BindingRegistry(crud.store, telemetry)
_METRIC_CODES = {n.get("metric_code") for n in crud.store.nodes()
                 if n.type == "TelemetryMetric"}


# ---- 鉴权（对齐平台 X-Internal-Token）----
def auth(x_internal_token: str = Header(default="")) -> bool:
    if not secrets.compare_digest(x_internal_token, INTERNAL_TOKEN):
        raise HTTPException(status_code=503, detail="内部令牌无效或未配置")
    return True


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": "1.0.0", "entities": len(crud.entities)}


# ---- ① 能力视图（平台消费）----
@app.get("/internal/ontology/capability-view")
def capability_view(robot_id: str | None = Query(default=None),
                    _: bool = Depends(auth)):
    return build_capability_view(crud.store, robot_id=robot_id)


# ---- ② 本体写操作（Gate A）----
class EntitiesRequest(BaseModel):
    entities: list[dict] = Field(default_factory=list)
    mode: str = "create"   # create=新建 / update=批量补丁


@app.post("/internal/ontology/entities")
def ingest_entities(req: EntitiesRequest, _: bool = Depends(auth)):
    try:
        if req.mode == "create":
            for e in req.entities:
                crud.create(e)
        else:
            crud.apply(req.entities)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail={
            "violations": [{"focus_node": v.focus_node, "path": v.path,
                            "message": v.message} for v in e.report.violations],
        })
    except CRUDError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "version": crud.version, "count": len(crud.entities)}


# ---- ③ 任务下发（Gate B + 受控动作）----
# 注意：本体 id 含斜杠（eo:task/carry-cup），路径参数用 :path 转换器匹配
@app.post("/internal/ontology/tasks/{task_id:path}/dispatch")
def dispatch_task(task_id: str, _: bool = Depends(auth)):
    result = registry.execute("task.dispatch", actor="platform", task_id=task_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return {"ok": result.ok, "messages": result.messages,
            "audit_log_id": result.audit_log_id}


# ---- ④ 本体细粒度遥测（测点注册表校验）----
class TelemetryPoint(BaseModel):
    entity_ref: str
    metric_code: str
    value: float
    time: str | None = None


class TelemetryRequest(BaseModel):
    points: list[TelemetryPoint] = Field(default_factory=list)


@app.post("/internal/ontology/telemetry")
def ingest_telemetry(req: TelemetryRequest, _: bool = Depends(auth)):
    for p in req.points:
        if p.metric_code not in _METRIC_CODES:
            raise HTTPException(status_code=422,
                                detail=f"测点 {p.metric_code} 未在 TelemetryMetric 注册表注册")
        telemetry.insert(p.entity_ref, p.metric_code, p.value, p.time)
    return {"ok": True, "count": len(req.points)}
