# 02 · Neo4j 节点-边映射规范

> 对象：LinkML Schema（v1.0.0）→ Neo4j 的确定性映射规则。
> 目的：任何一方（Python 加载器 / Go 后端 / 手工 Cypher）按本规范实现，产物图完全一致，且与 JSON-LD 双向无损。

## 1. 总则

| 规则 | 约定 |
|---|---|
| 节点标签 | = LinkML 类名；**所有节点同时携带 `:Entity` 标签**（全局唯一 id 的载体） |
| 节点属性名 | = 槽名（snake_case 原样） |
| 边类型 | = 槽名的 `UPPER_SNAKE_CASE`（如 `requires_capability` → `REQUIRES_CAPABILITY`） |
| 边方向 | = 槽的 domain → range |
| 节点标识 | `id` 属性存紧凑 IRI（`eo:robot/ti5`）；`entity_type` 属性存类名 |
| 单向存储 | 每个 Link 只存一个方向，查询双向遍历（Neo4j 关系天然无向遍历） |

## 2. 节点映射

### 2.1 标签与身份

```
MERGE (n:Entity {id: $id})            -- 全局唯一（:Entity 上有唯一约束）
SET   n:$Type,                         -- 类标签（多继承时 SET 多个）
      n.entity_type = $type,
      n += $props                      -- 标量属性批量并入
```

- 抽象类 `Entity` 不单独建标签；`TelemetryPoint` 不建标签（不落图库，ADR-7）。
- 多标签查询：`MATCH (n:Robot)` 走类型索引；跨类查询 `MATCH (n:Entity)`。

### 2.2 属性映射（标量槽 → 属性）

| LinkML 类型 | Neo4j 属性类型 | 说明 |
|---|---|---|
| `count` (integer) | Integer（64 位 long） | |
| `float` / 自定义数值类型（mass_kg 等） | Float（double） | |
| `boolean` | Boolean | |
| `string` | String | |
| `timestamp` (datetime) | String（ISO-8601） | 选 String 而非 Neo4j DateTime：与 JSON-LD/TimescaleDB 三库一致，避免时区序列化歧义 |
| 枚举 | String | 取值合法性由 SHACL 保证，不靠图库 |
| 多值标量槽 | 属性数组 | v1 无此场景，保留规则 |
| Link 槽 | **不落属性**，建边（§3） | |

- **空值策略**：缺省槽不写属性（不写 null）；读取方用 `COALESCE` 语义。
- **保留属性**：`id / entity_type / deprecated / created_at / updated_at / version`，业务槽不得重名。

### 2.3 运行态类管理

`Task / FaultEvent / ActionLog` 为快变/只增类，建议平台侧配置：任务终态（succeeded/failed/canceled）归档；FaultEvent/ActionLog 按 `detected_at/occurred_at` 定期归档到离线库（不属图库职责）。

## 3. 边映射

### 3.1 边类型总表（Link 槽 → 边）

| Link 槽 | 边类型 | 方向 |
|---|---|---|
| `located_at` | `LOCATED_AT` | Robot → Site |
| `has_part` | `HAS_PART` | Robot → BodyPart |
| `part_of` | `PART_OF` | BodyPart → BodyPart |
| `provides_capability` | `PROVIDES_CAPABILITY` | BodyPart → Capability |
| `requires_capability` | `REQUIRES_CAPABILITY` | Task → Capability |
| `involves_object` | `INVOLVES_OBJECT` | Task → Object |
| `assigned_to` | `ASSIGNED_TO` | Task → Robot |
| `at_site` | `AT_SITE` | Task → Site |
| `constrains` | `CONSTRAINS` | Constraint → Entity |
| `affects_bodypart` | `AFFECTS_BODYPART` | FaultMode / FaultEvent → BodyPart |
| `affects_capability` | `AFFECTS_CAPABILITY` | FaultMode → Capability |
| `of_mode` | `OF_MODE` | FaultEvent → FaultMode |
| `reported_by` | `REPORTED_BY` | FaultEvent → Robot |
| `parent` | `PARENT` | Site → Site |
| `target` | `TARGET` | ActionLog → Entity |
| `measures` | `MEASURES` | TelemetryMetric → Entity |
| `entity_ref` | `ENTITY_REF` | TelemetryPoint → Entity（仅 JSON-LD 交换时出现） |

### 3.2 边构建模板

```
MATCH (a:Entity {id: $src}), (b:Entity {id: $dst})
MERGE (a)-[r:REQUIRES_CAPABILITY]->(b)
```

### 3.3 边属性与限定关系（reification 边界）

- **v1：边不带属性。** Neo4j 支持关系属性，但 JSON-LD/RDF 无法无损表达关系属性，会破坏双向 round-trip——因此 v1 禁用。
- 需要限定关系（如「任务需要能力，且要求精度 ≥ x」）时，**物化（reification）模式**：

```
新增类 TaskCapabilityRequirement（id: eo:req/<uuid>）
  Task -REQUIRES-> (:TaskCapabilityRequirement) -OF_CAPABILITY-> Capability
  （需求参数如 min_precision 作为 Requirement 节点属性）
```

先新增类再使用，不直接在边上塞属性。

## 4. 约束与索引 DDL（随 Schema 版本维护）

```cypher
// ===== 唯一约束 =====
// 全局 id（:Entity 标签 + 唯一约束 = 跨类型 id 唯一）
CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE;
// 业务唯一键（对应 Schema unique_keys）
CREATE CONSTRAINT robot_serial_key    IF NOT EXISTS FOR (n:Robot)           REQUIRE n.serial    IS UNIQUE;
CREATE CONSTRAINT site_code_key       IF NOT EXISTS FOR (n:Site)            REQUIRE n.code      IS UNIQUE;
CREATE CONSTRAINT capability_code_key IF NOT EXISTS FOR (n:Capability)      REQUIRE n.code      IS UNIQUE;
CREATE CONSTRAINT faultmode_code_key  IF NOT EXISTS FOR (n:FaultMode)       REQUIRE n.mode_code IS UNIQUE;
CREATE CONSTRAINT metric_code_key     IF NOT EXISTS FOR (n:TelemetryMetric) REQUIRE n.metric_code IS UNIQUE;
// Object.object_code 可空，Neo4j 唯一约束天然跳过 null——直接建即可
CREATE CONSTRAINT object_code_key     IF NOT EXISTS FOR (n:Object)          REQUIRE n.object_code IS UNIQUE;

// ===== 热属性索引（按查询模式驱动，见 §6） =====
CREATE INDEX idx_entity_label      IF NOT EXISTS FOR (n:Entity)     ON (n.label);
CREATE INDEX idx_robot_status      IF NOT EXISTS FOR (n:Robot)      ON (n.status);
CREATE INDEX idx_task_status       IF NOT EXISTS FOR (n:Task)       ON (n.status);
CREATE INDEX idx_task_deadline     IF NOT EXISTS FOR (n:Task)       ON (n.deadline);
CREATE INDEX idx_bodypart_health   IF NOT EXISTS FOR (n:BodyPart)   ON (n.health);
CREATE INDEX idx_faultevent_time   IF NOT EXISTS FOR (n:FaultEvent) ON (n.detected_at);
CREATE INDEX idx_actionlog_time    IF NOT EXISTS FOR (n:ActionLog)  ON (n.occurred_at);
```

索引原则：先按真实查询模式加，不做预置全量索引；边查询走节点索引 + 关系类型扫描（Neo4j 5 关系类型有原生索引结构），v1 不需要边属性索引。

## 5. 批量加载规范

```cypher
// 节点（每批 ≤1000，UNWIND 批量；幂等）
UNWIND $rows AS row
MERGE (n:Entity {id: row.id})
SET n:Robot, n.entity_type = 'Robot', n += row.props

// 边（节点全部就位后执行；幂等）
UNWIND $rows AS row
MATCH (a:Entity {id: row.src}), (b:Entity {id: row.dst})
MERGE (a)-[r:REQUIRES_CAPABILITY]->(b)
```

- **加载顺序**：先全部节点、后全部边（两阶段）；引用完整性由 L1 SHACL 先校验，图库不承担。
- **更新语义**：`MERGE(id) SET += props` 幂等 upsert；`updated_at`/`version` 由写回方维护。
- **删除策略**：策划类（部件/能力/约束/模式/测点/物体）只置 `deprecated: true` 不物理删除；运行态（任务/事件/日志）按生命周期删除或归档；删节点前先删关联边（`DETACH DELETE`）。

## 6. 三库类型映射总表

| LinkML | JSON-LD / XSD | Neo4j | TimescaleDB |
|---|---|---|---|
| count | xsd:integer | Integer | BIGINT |
| float / mass_kg / torque_nm / force_n / speed_ms / percent / sampling_hz | xsd:double | Float | DOUBLE PRECISION |
| boolean | xsd:boolean | Boolean | BOOLEAN |
| string | xsd:string | String | TEXT |
| timestamp | xsd:dateTime | String（ISO-8601） | TIMESTAMPTZ |
| 枚举 | xsd:string（sh:in 约束） | String | TEXT（写入侧校验） |
| Link（对象槽） | IRI 引用 | Relationship | `entity_ref` TEXT（逻辑外键） |

## 7. 常用查询模板（图推理 = 遍历 + 规则）

**故障传播（模式库驱动）**：
```cypher
// 事件 → 模式 → 失效能力 → 受影响任务
MATCH (ev:FaultEvent {id: $event})-[r:OF_MODE]->(m:FaultMode)-[:AFFECTS_CAPABILITY]->(c:Capability)
      <-[:REQUIRES_CAPABILITY]-(t:Task)
RETURN c.code, t.id, t.label
```

**任务可达性（含指派机器人部件树）**：
```cypher
// 任务所需能力 ← 提供部件（限定在指派机器人的部件树内）
MATCH (t:Task {id: $task})-[:REQUIRES_CAPABILITY]->(c:Capability)
      <-[:PROVIDES_CAPABILITY]-(p:BodyPart)
OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(r:Robot)-[:HAS_PART]->(root:BodyPart)
RETURN c.code, p.id, p.health, r.serial
// 部件树闭包（递归，判断 p 是否属于 r）
MATCH (root:BodyPart)<-[:PART_OF*0..]-(p:BodyPart {id: $part})
```

**时序关联（图 → TimescaleDB 的键）**：
```cypher
MATCH (p:BodyPart {id: $part}) RETURN p.id
-- → SELECT * FROM telemetry WHERE entity_ref = $part AND metric = 'force_reading'
```

**反向根因**：任务失败 → 依赖链回溯：`(t)-[:REQUIRES_CAPABILITY]->(c)<-[:PROVIDES_CAPABILITY]-(p)` 中 health ∈ {fault, degraded} 的部件即根因候选。

## 8. JSON-LD ↔ Neo4j 双向转换

| 方向 | 规则 |
|---|---|
| 图 → JSON-LD | 节点 = `{id, type, 标量槽…}`；出边按 Link 槽聚合成 `{槽名: [目标 id…]}`（单值拍平） |
| JSON-LD → 图 | `id/type` 建节点（`entity_type` + 类标签）；Link 槽值逐条 `MERGE` 边 |
| 保真边界 | 边属性：v1 禁用（§3.3）；多标签：以 `entity_type` 为权威，导出只认它；节点属性顺序无关 |

round-trip 由 `tests/run_tests.py::test_jsonld_roundtrip` 锁定。
