// ============================================================================
// 具身本体论 · 图库 DDL（Neo4j）—— 随 Schema v1.0.0 维护
// 映射规范：docs/02-neo4j-mapping-spec.md（节点-边映射、类型映射、加载模板）
// 节点：(:Entity:<Class> {id, entity_type, ...props})，id = 紧凑 IRI
// 边  ：UPPER_SNAKE_CASE(Link 槽名)，方向 = domain → range
// ============================================================================

// ----- 全局唯一 id（:Entity 标签 + 唯一约束 = 跨类型唯一） -----
CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE;

// ----- 业务唯一键（对应 Schema unique_keys） -----
CREATE CONSTRAINT robot_serial_key    IF NOT EXISTS FOR (n:Robot)           REQUIRE n.serial    IS UNIQUE;
CREATE CONSTRAINT site_code_key       IF NOT EXISTS FOR (n:Site)            REQUIRE n.code      IS UNIQUE;
CREATE CONSTRAINT capability_code_key IF NOT EXISTS FOR (n:Capability)      REQUIRE n.code      IS UNIQUE;
CREATE CONSTRAINT faultmode_code_key  IF NOT EXISTS FOR (n:FaultMode)       REQUIRE n.mode_code IS UNIQUE;
CREATE CONSTRAINT metric_code_key     IF NOT EXISTS FOR (n:TelemetryMetric) REQUIRE n.metric_code IS UNIQUE;
// Object.object_code 可空：Neo4j 唯一约束天然跳过 null
CREATE CONSTRAINT object_code_key     IF NOT EXISTS FOR (n:Object)          REQUIRE n.object_code IS UNIQUE;

// ----- 热属性索引（按真实查询模式驱动） -----
CREATE INDEX idx_entity_label      IF NOT EXISTS FOR (n:Entity)     ON (n.label);
CREATE INDEX idx_robot_status      IF NOT EXISTS FOR (n:Robot)      ON (n.status);
CREATE INDEX idx_task_status       IF NOT EXISTS FOR (n:Task)       ON (n.status);
CREATE INDEX idx_task_deadline     IF NOT EXISTS FOR (n:Task)       ON (n.deadline);
CREATE INDEX idx_bodypart_health   IF NOT EXISTS FOR (n:BodyPart)   ON (n.health);
CREATE INDEX idx_faultevent_time   IF NOT EXISTS FOR (n:FaultEvent) ON (n.detected_at);
CREATE INDEX idx_actionlog_time    IF NOT EXISTS FOR (n:ActionLog)  ON (n.occurred_at);

// ============================================================================
// 常用遍历（图推理 = 遍历 + 规则，详见 docs/02 §7）
//
// 故障传播（模式库驱动）：
//   MATCH (ev:FaultEvent {id:$event})-[:OF_MODE]->(m:FaultMode)-[:AFFECTS_CAPABILITY]->(c:Capability)
//         <-[:REQUIRES_CAPABILITY]-(t:Task) RETURN c.code, t.id, t.label
//
// 任务可达性（含指派机器人部件树）：
//   MATCH (t:Task {id:$task})-[:REQUIRES_CAPABILITY]->(c:Capability)<-[:PROVIDES_CAPABILITY]-(p:BodyPart)
//   OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(r:Robot)-[:HAS_PART]->(root:BodyPart)
//   RETURN c.code, p.id, p.health, r.serial
//
// 部件树闭包（判断部件归属）：
//   MATCH (root:BodyPart)<-[:PART_OF*0..]-(p:BodyPart {id:$part})
//
// 反向根因：
//   MATCH (t:Task {id:$task})-[:REQUIRES_CAPABILITY]->(c:Capability)<-[:PROVIDES_CAPABILITY]-(p:BodyPart)
//   WHERE p.health IN ['fault','degraded'] RETURN p.id
// ============================================================================
