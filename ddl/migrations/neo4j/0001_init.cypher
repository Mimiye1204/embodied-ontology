// ============================================================================
// 迁移 0001 · 初始图库约束与索引（Neo4j）
// 约定见 ddl/MIGRATIONS.md：按序执行（Cypher 幂等），版本记入 :SchemaMigration。
// 映射规范：docs/02-neo4j-mapping-spec.md
// ============================================================================

// ----- 全局唯一 id（:Entity 标签 + 唯一约束 = 跨类型唯一） -----
CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE;

// ----- 业务唯一键（对应 Schema unique_keys） -----
CREATE CONSTRAINT robot_serial_key    IF NOT EXISTS FOR (n:Robot)           REQUIRE n.serial    IS UNIQUE;
CREATE CONSTRAINT site_code_key       IF NOT EXISTS FOR (n:Site)            REQUIRE n.code      IS UNIQUE;
CREATE CONSTRAINT capability_code_key IF NOT EXISTS FOR (n:Capability)      REQUIRE n.code      IS UNIQUE;
CREATE CONSTRAINT faultmode_code_key  IF NOT EXISTS FOR (n:FaultMode)       REQUIRE n.mode_code IS UNIQUE;
CREATE CONSTRAINT metric_code_key     IF NOT EXISTS FOR (n:TelemetryMetric) REQUIRE n.metric_code IS UNIQUE;
CREATE CONSTRAINT object_code_key     IF NOT EXISTS FOR (n:Object)          REQUIRE n.object_code IS UNIQUE;

// ----- 热属性索引（按真实查询模式驱动） -----
CREATE INDEX idx_entity_label      IF NOT EXISTS FOR (n:Entity)     ON (n.label);
CREATE INDEX idx_robot_status      IF NOT EXISTS FOR (n:Robot)      ON (n.status);
CREATE INDEX idx_task_status       IF NOT EXISTS FOR (n:Task)       ON (n.status);
CREATE INDEX idx_task_deadline     IF NOT EXISTS FOR (n:Task)       ON (n.deadline);
CREATE INDEX idx_bodypart_health   IF NOT EXISTS FOR (n:BodyPart)   ON (n.health);
CREATE INDEX idx_faultevent_time   IF NOT EXISTS FOR (n:FaultEvent) ON (n.detected_at);
CREATE INDEX idx_actionlog_time    IF NOT EXISTS FOR (n:ActionLog)  ON (n.occurred_at);

// 迁移版本登记
MERGE (m:SchemaMigration {version: 1})
  SET m.description = 'init: 全局唯一 id + 业务唯一键约束 + 热属性索引',
      m.applied_at = datetime();
