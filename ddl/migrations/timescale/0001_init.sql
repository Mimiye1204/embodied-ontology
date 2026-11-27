-- ============================================================================
-- 迁移 0001 · 初始时序 schema（TimescaleDB）
-- 约定见 ddl/MIGRATIONS.md：按序执行，版本记入 schema_migrations。
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 迁移版本登记表
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 时序表：entity_ref 逻辑外键关联本体实体（Neo4j 节点 .id / JSON-LD @id）
CREATE TABLE IF NOT EXISTS telemetry (
    time       TIMESTAMPTZ      NOT NULL,  -- 采样时间（hypertable 分区键）
    entity_ref TEXT             NOT NULL,  -- 外键 → 本体实体 id（如 eo:part/ti5/six-axis-force）
    metric     TEXT             NOT NULL,  -- 测点名：joint_angle / force_reading / battery / task_progress
    value      DOUBLE PRECISION NOT NULL   -- 数值
);

SELECT create_hypertable('telemetry', 'time', if_not_exists => TRUE);

-- 「外键关联」查询路径：按实体 + 测点 + 时间窗取序列
CREATE INDEX IF NOT EXISTS idx_telemetry_entity_metric_time
    ON telemetry (entity_ref, metric, time DESC);

INSERT INTO schema_migrations (version, description)
VALUES (1, 'init: telemetry hypertable + entity/metric/time 复合索引')
ON CONFLICT (version) DO NOTHING;
