-- ============================================================================
-- 具身本体论 · 时序库 DDL（TimescaleDB）
-- 时序数据通过 entity_ref 外键关联本体图实体（Neo4j 节点 .id / JSON-LD @id）
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS telemetry (
    time       TIMESTAMPTZ       NOT NULL,  -- 采样时间（hypertable 分区键）
    entity_ref TEXT              NOT NULL,  -- 逻辑外键 → 本体实体 id（如 eo:six_axis_force）
    metric     TEXT              NOT NULL,  -- 测点名：joint_angle / force_reading / battery / task_progress
    value      DOUBLE PRECISION  NOT NULL   -- 数值
);

SELECT create_hypertable('telemetry', 'time', if_not_exists => TRUE);

-- 「外键关联」查询路径：按实体 + 测点 + 时间窗取序列
CREATE INDEX IF NOT EXISTS idx_telemetry_entity_metric_time
    ON telemetry (entity_ref, metric, time DESC);

-- 保留策略（示例：原始数据保留 30 天，之后压缩/降采样，按需启用）
-- SELECT add_retention_policy('telemetry', INTERVAL '30 days');

-- ----------------------------------------------------------------------------
-- 若实体对象库也落 PostgreSQL（而非 Neo4j 图库），可升级为真外键：
--   CREATE TABLE ontology_entity (
--       id   TEXT PRIMARY KEY,     -- 对应 Neo4j 节点 .id / JSON-LD @id 的紧凑形式
--       type TEXT NOT NULL,
--       properties JSONB NOT NULL DEFAULT '{}'
--   );
--   ALTER TABLE telemetry
--     ADD CONSTRAINT fk_telemetry_entity
--     FOREIGN KEY (entity_ref) REFERENCES ontology_entity(id);
-- ----------------------------------------------------------------------------
