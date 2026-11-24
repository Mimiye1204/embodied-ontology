# 03 · SHACL 校验规则框架

> 对象：实例（ABox）的完整性校验体系。
> 原则：**SHACL 只做声明式静态校验；计算性/状态化推理归规则引擎**。三层分工、四道校验门、严重度分级，扩展有固定路径。

## 1. 三层校验架构

```
L0 结构层（自动生成）   LinkML Schema → SHACL 形状（每类一个 NodeShape，closed）
        │ 校验：类型/枚举/数值域/必填/多重性/Link 目标类/唯一键
L1 领域层（自动+手写）  引用完整性（自动）+ 跨实体不变量（shapes/domain.ttl 手写）
        │ 校验：Link 目标存在、能力有提供者、测点已注册、故障部件归属…
L2 规则层（Python）     eo/rules —— 跨源（图+时序）、计算、状态化
        │ 校验：力矩/负载/位形拦截、任务可达性、故障传播、归纳写回
```

**边界判定表（一条校验放哪层）**：

| 校验性质 | 放哪层 |
|---|---|
| 单个实体的结构/取值合法（不依赖其他实体） | L0（Schema 即表达） |
| 单个实体结构合法但 Schema 表达不了（如「属性 A 存在则 B 必存在」） | L1 手写形状 |
| 跨实体静态不变量（引用存在、唯一、归属一致） | L1（引用完整性自动 + 手写） |
| 需要计算（力矩=重量×力臂）或读时序库（当前力读数） | L2 |
| 随时间变化的状态判断（健康状态→可达性） | L2 |

## 2. L0：LinkML → SHACL 生成规则（`eo/shacl/shapes.py`）

| LinkML 构造 | SHACL 构造 |
|---|---|
| 类 `X`（具体类） | `eo:XShape a sh:NodeShape; sh:targetClass eo:X` |
| 类有标识符槽 | `sh:nodeKind sh:IRI`（id 即 @id，不落属性） |
| —（默认） | `sh:closed true` + `sh:ignoredProperties (rdf:type)`（RDF 列表形式） |
| `required: true` | `sh:minCount 1` |
| 非 `multivalued` 槽 | `sh:maxCount 1` |
| 枚举 range | `sh:in (v1 v2 …)`（**RDF 列表**，多值 sh:in 会 ConstraintLoadError） |
| 标量 range | `sh:datatype xsd:…`（datetime 槽的 @context 已带 `xsd:dateTime` 强制） |
| 自定义类型 `minimum_value`/`maximum_value` | `sh:minInclusive` / `sh:maxInclusive` |
| Link range = 具体类 | `sh:class eo:X` |
| Link range = 抽象基类（Entity） | `sh:nodeKind sh:IRI`（无 RDFS 蕴含时 sh:class 不匹配子类） |
| `unique_keys` | SPARQL 唯一形状（§5 模式 A；可选业务键自动跳过缺席值） |

**生成确定性**：生成是纯函数（同 Schema → 同形状）；提交 `generated/shapes.ttl` 进版本库，CI 再生成一次 diff 为空即「无漂移」。

## 3. L1：领域层

### 3.1 引用完整性（自动生成）

每个 Link 槽自动生成「目标必须存在于数据集」形状（模式 B）。悬空引用 = 写入前拦截，这是「加载器二阶段建图」的安全网。

### 3.2 手写领域形状（`src/eo/shacl/domain.ttl`）

示例（v1 内置 3 条，模式见 §5）：

| 形状 | 不变量 |
|---|---|
| `eo:CapabilityHasProviderShape` | 能力必须有 ≥1 个部件提供 |
| `eo:MetricRegisteredShape` | TelemetryPoint.metric_code 必须命中 TelemetryMetric 注册表 |
| `eo:FaultPartBelongsToReporterShape` | FaultEvent 的 affects_bodypart 必须属于 reported_by 机器人的部件树 |

### 3.3 扩展流程

在 `domain.ttl` 追加 NodeShape（复用 §5 模式）→ 重跑全量校验 → 提交。**领域不变量不写进代码**。

## 4. L2：规则层（`eo/rules`）

SHACL 校验通过 ≠ 任务可执行。L2 负责：

- **动作拦截**（intercept.py）：读约束库（Constraint.expression/threshold/suggested_rewrite）+ 物体属性 → 拦截项 + 改写建议（数据驱动，ADR-5）
- **任务可达性**（reachability.py）：任务 → 能力 → 部件覆盖 + 健康状态 + 指派机器人部件树 → verdict 写回 Task（ADR-6）
- **故障传播**（faults.py）：FaultEvent → FaultMode 模式库 → 失效能力 → 受影响任务（正向）；任务失败 → 依赖链回溯根因（反向）
- **归纳写回**：时序库读数 → 检测（滑移）→ 写回属性 → 重跑规则（写回后的实体仍受 L0/L1 约束，闭环）

## 5. SPARQL 形状模式库（L1 用）

> 引擎实现约定：pyshacl 0.40 只实现 `sh:select` 形式（**SELECT 每返回一行 = 一条违规**，`$this` 由校验器预绑定为焦点节点）。语义等价于 SHACL 规范的 `sh:ask`（true = 违规）。

**模式 A · 业务唯一键**：

```turtle
eo:RobotSerialUniqueShape a sh:NodeShape ;
  sh:targetClass eo:Robot ;
  sh:sparql [ a sh:SPARQLConstraint ;
    sh:message "serial 重复：{$this}" ;
    sh:prefixes eo: ;
    sh:select """SELECT $this ?other WHERE { $this eo:serial ?v .
                    ?other eo:serial ?v . FILTER (?other != $this) }""" ] .
```

**模式 B · 引用完整性**（目标在数据集中无任何三元组 = 悬空）：

```turtle
eo:RequiresCapabilityExistsShape a sh:NodeShape ;
  sh:targetSubjectsOf eo:requires_capability ;
  sh:sparql [ a sh:SPARQLConstraint ;
    sh:message "悬空引用：{$this} 的 requires_capability 指向不存在的实体" ;
    sh:prefixes eo: ;
    sh:select """SELECT $this ?o WHERE { $this eo:requires_capability ?o .
                    FILTER NOT EXISTS { ?o ?p ?v } }""" ] .
```

**模式 C · 跨实体存在性**（能力必须有提供者）：

```turtle
eo:CapabilityHasProviderShape a sh:NodeShape ;
  sh:targetClass eo:Capability ;
  sh:sparql [ a sh:SPARQLConstraint ;
    sh:message "能力 {$this} 没有任何部件提供" ;
    sh:prefixes eo: ;
    sh:select """SELECT $this WHERE {
                    FILTER NOT EXISTS { ?p eo:provides_capability $this } }""" ] .
```

## 6. 校验门（Gates）

| 门 | 触发时机 | 层 | 失败处理 |
|---|---|---|---|
| **A 写入前** | 平台/加载器 ingest 任何实体（含写回） | L0 + L1 | Violation=拒绝写入并回报告；Warning=放行+告警 |
| **B 执行前** | 任务下发/动作执行前 | L2 拦截 + L1 抽查 | 拦截→改写→重校验（闭环）；无法改写→任务置 intercepted |
| **C 导出前** | JSON-LD 发布给外部系统/前端同步 | L0 | 失败=拒绝导出（保证交换格式永不出脏数据） |
| **D 定时** | 每日全量：引用完整性+孤儿检测+唯一键 | L1 | 出报告→平台操作日志/告警 |

## 7. 严重度与处理策略

| sh:severity | 含义 | 处理 |
|---|---|---|
| `sh:Violation` | 数据非法，不可入库 | Gate A/C 拒绝 |
| `sh:Warning` | 可疑但可运行（如 degraded 部件） | 放行 + 平台告警 |
| `sh:Info` | 提示（如可优化项） | 仅报告 |

默认全 Violation；个别形状可显式降级（在形状上加 `sh:severity sh:Warning`）。

## 8. 校验报告格式（→ 平台操作日志/UI）

pyshacl 文本报告之上的结构化导出（validate.py 负责）：

```json
{
  "gate": "A",
  "conforms": false,
  "violations": [
    {
      "focus_node": "eo:task/8f2c…",
      "result_path": "eo:requires_capability",
      "severity": "sh:Violation",
      "message": "悬空引用：…指向不存在的实体",
      "source_shape": "eo:RequiresCapabilityExistsShape"
    }
  ]
}
```

消息规范：中文 + 含焦点节点 id（`{$this}` 展开），平台侧可点击跳转实体。

## 9. 实现对照（本仓库）

| 框架组件 | 实现 |
|---|---|
| L0 生成 | `src/eo/shacl/shapes.py`（含 unique_keys → 模式 A；BNode 确定性 id，可复现） |
| L1 自动 | `shapes.py::build_l1_shapes()`（模式 B，全 Link 槽引用完整性） |
| L1 手写 | `src/eo/shacl/domain.ttl` |
| 校验执行 | `src/eo/shacl/validate.py`（L0+L1 合并为 shacl_graph，pyshacl） |
| 结构化报告（§8） | `validate_entities_structured()` → `ValidationReport/Violation` |
| Gate A 落地 | `src/eo/crud.py`（OntologyCRUD：所有写操作先校验后提交，失败回滚；CLI=`cli.py`） |
| L2 | `src/eo/rules/`（intercept/reachability/faults/domain） |
| 形状产物 | `generated/shapes.ttl`（提交版本库，漂移检测） |
