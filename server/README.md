# 本体引擎 REST API（本地草稿 · 未入仓库）

对齐 robot-dispatch-server 风格：`/internal/*` 走 `X-Internal-Token` 鉴权（常量时间比对，不匹配返回 503）。

## 运行

```bash
cd C:\Users\周艺\embodied-ontology-engine
.venv/Scripts/python.exe -m uvicorn server.app:app --host 0.0.0.0 --port 8091
```

令牌：环境变量 `ONTOLOGY_INTERNAL_TOKEN`（默认 `test-ontology-token`）。

## 端点（对应 docs/06 §6）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/healthz` | 健康检查 |
| GET | `/internal/ontology/capability-view?robot_id=eo:robot/ti5` | 能力视图（平台消费）|
| POST | `/internal/ontology/entities` | 本体写操作（Gate A）|
| POST | `/internal/ontology/tasks/{id}/dispatch` | 任务下发（Gate B + 动作 + 审计）|
| POST | `/internal/ontology/telemetry` | 本体细粒度遥测（测点注册表校验）|

## 调用示例

```bash
# 能力视图
curl -H "X-Internal-Token: test-ontology-token" \
  http://127.0.0.1:8091/internal/ontology/capability-view

# 写一个实体（Gate A，非法会被 422 拒绝）
curl -X POST -H "X-Internal-Token: test-ontology-token" -H "Content-Type: application/json" \
  -d '{"entities":[{"id":"eo:object/pen","type":"Object","label":"笔","weight_kg":0.02,"surface":"dry","created_at":"2026-11-27T10:00:00+08:00"}]}' \
  http://127.0.0.1:8091/internal/ontology/entities

# 下发任务
curl -X POST -H "X-Internal-Token: test-ontology-token" \
  http://127.0.0.1:8091/internal/ontology/tasks/eo:task/carry-cup/dispatch

# 细粒度遥测
curl -X POST -H "X-Internal-Token: test-ontology-token" -H "Content-Type: application/json" \
  -d '{"points":[{"entity_ref":"eo:part/ti5/six-axis-force","metric_code":"force_reading","value":4.0}]}' \
  http://127.0.0.1:8091/internal/ontology/telemetry
```

## 状态

- 草稿：数据从 `examples/fleet.json` 内存装载，重启即重置；生产应接持久化存储（Neo4j/TimescaleDB）。
- 未入 git 仓库（server/ 目录 untracked）。
