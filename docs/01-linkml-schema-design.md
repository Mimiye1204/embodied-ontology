# 01 · LinkML 本体 Schema 设计

> 对象：`schema/embodied_ontology.yaml`（v1.0.0）
> 定位：单一事实来源（TBox），驱动 Neo4j 映射（docs/02）、SHACL 形状（docs/03）、JSON-LD @context、图加载器。改这里一处，下游全部跟随。

## 1. 定位与设计目标

| 目标 | 落地方式 |
|---|---|
| 多机器人编队 | Robot/Site 台账；任务指派到机器人；可达性按「指派机器人」判定 |
| 平台对接 | 业务唯一键（serial/code/mode_code/metric_code）对接调度中台设备台账 |
| 写回受控可审计 | ActionLog（谁、对谁、做了什么、结果），对应 Palantir ActionType 思想 |
| 故障传播可维护 | FaultMode 故障模式库——传播依据是数据，不是代码 |
| 时序外键有约束 | TelemetryMetric 测点注册表——TimescaleDB 的 (entity, metric) 键域来源 |
| 数值可校验 | 单位入类型（mass_kg/torque_nm…），数值域由 SHACL L0 强制 |
| 可演进 | deprecated 标记 + 语义化版本 + 迁移策略（§7） |

**非目标**：不做 OWL 描述逻辑深度推理（类层级保持浅平）；演绎/溯因/归纳全部交给规则引擎（L2 层），SHACL 只做声明式完整性。

## 2. 命名空间与 ID 规范

- 本体 IRI 基址：`https://ontology.huilun.cn/embodied/`（前缀 `eo:`；**上线前替换为正式域名**，仅改 `prefixes` 一处）
- 存储/交换统一使用**紧凑 IRI**（CURIE）作为实体 id：

| 实体类别 | ID 模式 | 生成方式 | 示例 |
|---|---|---|---|
| 场地 | `eo:site/<code>` | 人工编码 | `eo:site/hq` |
| 机器人 | `eo:robot/<serial>` | 出厂序列号 | `eo:robot/ti5` |
| 部件 | `eo:part/<robot>/<路径>` | 部件树路径 | `eo:part/ti5/arm/wrist` |
| 能力 | `eo:cap/<code>` | 能力注册码 | `eo:cap/force-control` |
| 物体 | `eo:object/<code>` | 物体注册码（未知物体临时 UUID） | `eo:object/cup` |
| 约束 | `eo:constraint/<code>` | 人工编码 | `eo:constraint/wrist-torque-limit` |
| 故障模式 | `eo:faultmode/<code>` | 人工编码 | `eo:faultmode/force-sensor-failure` |
| 任务 | `eo:task/<uuid>` | 系统生成 UUID | `eo:task/8f2c9a...` |
| 故障事件/动作日志 | `eo:event/<uuid>` / `eo:log/<uuid>` | 系统生成 UUID | — |
| 测点定义 | `eo:metric/<code>` | 人工编码 | `eo:metric/force-reading` |

**规则**：策划类实体（部件/能力/约束/模式/测点/物体）用人工可读编码，运行态实体（任务/事件/日志）用 UUID；id 一经分配**不可变**；淘汰用 `deprecated: true` 标记而非删除。

## 3. 类目录（ObjectType，13 个）

| 类 | 职责 | 生命周期 | 备注 |
|---|---|---|---|
| `Entity` | 抽象基类：id/label/溯源 | — | 不直接实例化 |
| `Site` | 场地（多场地调度） | 慢变 | 支持 parent 层级 |
| `Robot` | 机器人台账 | 慢变 | serial 业务唯一键 |
| `BodyPart` | 部件树节点；健康/能力载体 | 慢变 | part_of 成树，根挂在 Robot.has_part |
| `Capability` | 能力注册 | 慢变 | 提供者经 provides_capability 反向遍历 |
| `Object` | 环境物体（affordance） | 慢变 | object_code 可空=未知物体 |
| `Task` | 任务：需求+指派+生命周期 | 快变 | verdict 为规则引擎写回缓存 |
| `Constraint` | 约束库（拦截依据） | 慢变 | expression + suggested_rewrite 数据化 |
| `FaultMode` | 故障模式库（传播依据） | 慢变 | 模式→部件/能力，见 ADR-1 |
| `FaultEvent` | 故障事件 | 快变 | 经 of_mode 关联模式库 |
| `ActionLog` | 写回审计 | 只增 | 见 ADR-3 |
| `TelemetryMetric` | 测点注册表 | 慢变 | 时序库键域，见 ADR-2 |
| `TelemetryPoint` | 测点值（交换窗口用） | 高频 | 不落图库，见 ADR-7 |

## 4. Property 与 Link 设计

**区分规则**：槽的 `range` 指向类 → Link（图边）；指向标量/枚举 → Property（属性）。

### 4.1 单位与数值域

单位语义进入类型定义而非槽名后缀兜底：`mass_kg / torque_nm / force_n / speed_ms / percent / sampling_hz / retention_days`。数值域（`minimum_value`/`maximum_value`）由 L0 SHACL 强制（如 `weight_kg ≥ 0`、`priority ∈ [0,10]`）。

### 4.2 Link 清单（方向 = 存储方向，遍历可双向）

| Link 槽 | domain → range | 多重性 | 设计理由 |
|---|---|---|---|
| `located_at` | Robot → Site | 0..1 | 机器人当前位置 |
| `has_part` | Robot → BodyPart | 0..n | 部件树根（每个机器人一棵或多棵树） |
| `part_of` | BodyPart → BodyPart | 0..1 | 部件树 |
| `provides_capability` | BodyPart → Capability | 0..n | 能力供给（可达性/故障传播遍历主轴） |
| `requires_capability` | Task → Capability | **1..n** | 任务能力需求（必填） |
| `involves_object` | Task → Object | 0..1 | 任务作用物体 |
| `assigned_to` | Task → Robot | 0..1 | 指派；空=未指派（按全队评估） |
| `at_site` | Task → Site | 0..1 | 已指派时从机器人推导 |
| `constrains` | Constraint → Entity | **1..1** | 约束作用对象（部件/能力/任务） |
| `affects_bodypart` | FaultMode → BodyPart | 0..n | 模式影响的部件 |
| `affects_capability` | FaultMode → Capability | 0..n | 模式导致失效的能力（传播依据） |
| `of_mode` | FaultEvent → FaultMode | 0..1 | 事件关联模式库；空=按直接关联部件传播 |
| `affects_bodypart` | FaultEvent → BodyPart | **1..1** | 事件直接影响的部件 |
| `reported_by` | FaultEvent → Robot | 0..1 | 上报机器人 |
| `parent` | Site → Site | 0..1 | 场地层级 |
| `target` | ActionLog → Entity | 0..1 | 审计对象 |
| `measures` | TelemetryMetric → Entity | 0..1 | 测点测量对象 |
| `entity_ref` | TelemetryPoint → Entity | **1..1** | 时序外键（与 metric_code 组成联合键） |

### 4.3 必填策略

- 全实体必填：`id / label / created_at`
- 业务键必填：Site.code、Robot.serial、Capability.code、FaultMode.mode_code、TelemetryMetric.metric_code
- 关键 Link 必填：Task.requires_capability（≥1）、Constraint.constrains、FaultEvent.affects_bodypart、TelemetryPoint.entity_ref
- 其余可空（缺省=未知，不写假值）

## 5. 枚举目录

`RobotStatus`(online/offline/maintenance/decommissioned) · `TaskStatus`(pending/dispatched/executing/succeeded/failed/canceled/intercepted) · `HealthStatus`(ok/degraded/fault) · `SurfaceType`(dry/slippery/rough) · `ConstraintType`(torque/load/pose/gripper/speed/workspace) · `Severity`(info/warning/critical) · `FaultStatus`(active/acknowledged/resolved) · `MetricValueType`(float/int/bool) · `VerdictType`(feasible/constrained/infeasible/rewrite)

## 6. 关键设计决策（ADR）

- **ADR-1 FaultMode 故障模式库**：故障传播从「代码里硬编码遍历」变为「模式库数据 + 事件关联模式」。新增故障场景=加一条模式数据，不用改代码。
- **ADR-2 TelemetryMetric 测点注册表**：TimescaleDB 写入的 `(entity_ref, metric)` 必须命中注册表（L1 SHACL 校验），杜绝脏测点；注册表同时给出值类型/单位/量程/采样率/保留期。
- **ADR-3 ActionLog 写回审计**：本体所有写操作（下发/拦截/改写/执行）落审计日志，对接平台操作日志与权限审计。
- **ADR-4 `status` 槽用 `slot_usage` 按类收窄**：Robot.status=RobotStatus、FaultEvent.status=FaultStatus，避免全局槽二义。
- **ADR-5 位形能力不设布尔属性**：演示版的 `has_hip` 删除。能否「坐」= 能力 `eo:cap/sitting` 是否存在提供者 + 约束 `pose`（constrains→leg）是否命中——能力与限制分离，数据驱动。
- **ADR-6 `Task.verdict` 是计算缓存**：规则引擎（L2）计算可达性后写回，供平台列表页直接读；任何健康/能力变更后需重算（平台侧失效策略）。
- **ADR-7 TelemetryPoint 不落图库**：高频数据只进 TimescaleDB；该类的存在是为了「故障取证等小窗口」能以 JSON-LD 交换，不进 Neo4j。

## 7. 版本与演进

- 语义化版本：破坏性变更（删类/改槽范围）升大版本；加类/加槽升小版本。
- 淘汰流程：`deprecated: true` → 观察一个版本 → 下个大版本删除。
- 迁移安全表：

| 变更 | 安全性 | 要求 |
|---|---|---|
| 加类 / 加可选槽 | 安全 | 重新生成形状与 @context，全量校验 |
| 加必填槽 | 需回填 | 先加为可选→回填→再改必填 |
| 改槽 range（放宽枚举值） | 安全 | 已存数据仍合法 |
| 改槽 range（收窄/改类型） | 破坏性 | 升大版本，数据先迁移 |
| 删类/删槽 | 破坏性 | 先 deprecated 一个版本 |

- Schema 变更流程：改 schema → 重跑 `eo.shacl` 生成（L0 形状 + @context 漂移检测）→ 全量实例校验 → 平台发布。

## 8. 与演示版（0.1）差异清单

| 演示版 | v1.0.0 | 理由 |
|---|---|---|
| 无 Robot/Site | Robot 台账 + Site 场地 | 多机器人编队 |
| 无任务生命周期 | Task.status/priority/deadline/assigned_to | 调度平台对接 |
| 无故障模式库 | FaultMode | ADR-1 |
| 无测点注册表 | TelemetryMetric | ADR-2 |
| 无审计 | ActionLog | ADR-3 |
| 无溯源 | created_at/updated_at/version/deprecated | 生产数据治理 |
| `has_hip` 布尔属性 | Constraint(pose) | ADR-5 |
| 任务/事件用语义 id | 运行态 UUID（示例数据仍用可读码） | 生产唯一性 |
| `id` range string | uriorcurie | 规范 IRI 身份 |
