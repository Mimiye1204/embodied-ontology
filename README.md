# 具身本体论引擎（Embodied Ontology Engine）

面向 T170C 的具身本体论工程实现（Schema v1.1.0）：
**LinkML 定义 Schema → SHACL 校验（L0+L1）→ JSON-LD 全域交换 → Neo4j 图存储 → 自研规则引擎（L2）→ TimescaleDB 时序库**。

> 设计文档（先读这四份）：
> - [docs/01-linkml-schema-design.md](docs/01-linkml-schema-design.md) — Schema 设计（13 个 ObjectType、ID 规范、ADR、演进策略）
> - [docs/02-neo4j-mapping-spec.md](docs/02-neo4j-mapping-spec.md) — 节点-边映射规范（类型映射、约束/索引 DDL、批量加载、查询模板）
> - [docs/03-shacl-framework.md](docs/03-shacl-framework.md) — 校验框架（三层架构、四道校验门、SPARQL 形状模式库）
> - [docs/04-动力层设计.md](docs/04-动力层设计.md) — 时序属性绑定 · 规则引擎框架 · Action 绑定模型
> - [docs/05-能力视图与平台对接.md](docs/05-能力视图与平台对接.md) — 输出给调度中台的能力视图 Schema + JSON-LD 过滤导出

## 架构

```
schema/embodied_ontology.yaml （LinkML，单一事实来源，v1.0.0）
  ├─ 运行时内省（eo/schema.py: SchemaView）
  ├─→ L0 SHACL 形状自动生成（eo/shacl/shapes.py：closed/枚举/数值域/唯一键）
  ├─→ L1 形状（引用完整性自动生成 + domain.ttl 手写领域不变量）
  └─→ JSON-LD @context 自动推导（eo/jsonld/context.py）
       │
 数据层 ABox：examples/fleet.json（T170C 51 实体）──Gate A SHACL──→ 图存储
       │                                              （写入前校验 L0+L1）
 存储层：GraphStore 接口 ── MemoryStore（本地） / Neo4jStore（生产，docs/02 规范）
       │
 计算层（L2 规则引擎，eo/rules/）：正向链+增量打印（演绎/约束/归纳）
       ├─ 动作拦截 intercept.py —— 约束库驱动（torque/load/pose/surface → 改写建议）
       ├─ 任务可达性 reachability.py —— 能力覆盖 + 健康状态 + 指派机器人部件树
       └─ 故障传播 faults.py —— FaultMode 模式库驱动（正向级联 + 反向根因）
       │  ▲
       ▼  │ 归纳写回（滑移检测 → surface=slippery → 力度×1.5，写回后仍过 SHACL）
 时序层：TelemetryStore 接口 ── SqliteTelemetryStore（本地）
       / TimescaleTelemetryStore（生产，ddl/timescale_schema.sql）
       测点键 (entity_ref, metric) 必须命中 TelemetryMetric 注册表（L1 校验）
       │
 交换层：JSON-LD 双向 round-trip（export/import，57 实体语义无损，测试锁定）
```

## 快速开始

```bash
# 依赖（.venv 已建；重装走清华镜像）
.venv/Scripts/python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 端到端验证（9 段流水线，负例演示 SHACL 拦截）
.venv/Scripts/python.exe demo.py

# 本体底座整体自检（Schema→对象→链路→规则→动作→导出→视图 联调，10 段）
.venv/Scripts/python.exe selfcheck.py

# 单元测试（65 项，按关注点分文件：对象/链路/规则/校验/动作/时序）
.venv/Scripts/python.exe -m pytest tests/ -q          # 全量
.venv/Scripts/python.exe -m pytest tests/test_rules.py -v   # 只看规则执行结果
.venv/Scripts/python.exe tests/run_tests.py           # 等价入口

# 浏览器可视化报告（本体图 + 正常/故障切换 + 推理面板）
.venv/Scripts/python.exe report.py

# 本体能力视图（输出给调度中台的契约，纯 JSON / JSON-LD）
.venv/Scripts/python.exe cli.py view --robot eo:robot/ti5
.venv/Scripts/python.exe cli.py view --jsonld --out generated/view.jsonld

# Object/Property/Link CRUD（所有写操作经 Gate A SHACL 校验，违规拒绝+回滚）
.venv/Scripts/python.exe cli.py get eo:robot/ti5
.venv/Scripts/python.exe cli.py list --type Task
.venv/Scripts/python.exe cli.py set eo:object/cup weight_kg 0.35
.venv/Scripts/python.exe cli.py link eo:task/carry-cup eo:object/door involves_object
.venv/Scripts/python.exe cli.py create '{"id":"eo:object/pen","type":"Object","label":"笔","weight_kg":0.02,"surface":"dry","created_at":"2026-11-24T10:00:00+08:00"}'
.venv/Scripts/python.exe cli.py delete eo:object/pen [--physical]   # 默认软删除(deprecated)
.venv/Scripts/python.exe cli.py validate
```

## 关键能力演示（demo 输出）

- **任务可达性**：任务→能力→部件覆盖 + 健康状态判定（抓鸡蛋依赖力控，六维力故障后不可达；端杯子走包握不受影响）
- **约束库拦截**：满水壶（力矩 0.6 > 0.5）→ 先减负；箱子（力矩+负载双超）→ 底盘推行；坐下（无臀部位形）→ 改写任务意义；湿滑杯 → 力度 ×1.5
- **模式库故障传播**：事件 → 模式 force-sensor-failure → 力控失效 → 抓鸡蛋/捏硬币失败；端杯子依赖隔离不受影响；反向根因回溯到六维力传感器
- **归纳闭环**：力读数骤降 67% → 写回 surface=slippery → 规则重跑 → grip_factor=1.5 → JSON-LD 带出
- **SHACL 七类负例拦截**：唯一键冲突 / 悬空引用 / 未注册测点 / 能力无提供者 / 负重量 / 枚举越界 / 未知属性
- **CRUD + Gate A 落地**：`eo/crud.py` 唯一写路径（Object 实体 / Property 标量属性 / Link 关系的 create/get/update/delete/link/unlink），每次写=补丁浅合并→全量 SHACL→原子提交，失败回滚+结构化违规报告（focus_node/path/message/severity/source_shape）；CLI 即 `cli.py`；仿真与 CRUD 共用同一条写路径
- **动力层三件套**（docs/04）：时序属性绑定（测点注册表 binds_to → 动态属性物化，聚合算子 last/avg/…）、规则引擎框架（RuleSpec 数据化规则/优先级/证明链 explain()/规则→动作声明式绑定）、Action 模型（6 个受控动作，参数+目标类型校验+自动审计）；监测规则→写回→重推的闭环见 sim slip_loop 场景

## 扩展路径

| 想做什么 | 改哪里 |
|---|---|
| 加对象类型/属性 | `schema/embodied_ontology.yaml`（形状/@context/加载器自动跟随，见 docs/01 §7 迁移安全表） |
| 加实体/改数据 | `cli.py create/update/...` 或直接改 `examples/fleet.json`（Gate A 自动校验） |
| 加领域不变量 | `src/eo/shacl/domain.ttl`（docs/03 §5 模式库） |
| 加推理规则 | `src/eo/rules/domain.py`（正向链增量打印） |
| 加故障场景 | 加一条 FaultMode 数据（不改代码） |
| 程序化读写本体 | `eo/crud.py` 的 `OntologyCRUD`（唯一写路径，REST 包装直接加在它上面） |
| 切生产存储 | `Neo4jStore` + `TimescaleTelemetryStore`（接口不变；DDL 见 ddl/） |

## 生产切换清单

1. Neo4j：执行 `ddl/neo4j_schema.cypher` → 工厂换 `Neo4jStore`
2. TimescaleDB：执行 `ddl/timescale_schema.sql` → 工厂换 `TimescaleTelemetryStore`
3. 命名空间：上线前把 `eo:` 前缀换成正式域名（schema 一处 + docs/01 §2）
