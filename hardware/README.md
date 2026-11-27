# 硬件蓝图 → 本体的自动生成（docs/01 §5 方法C）

一份声明式**硬件方案**（YAML/JSON）自动生成：
- **Object**：Robot / BodyPart（部件树）/ Capability / Constraint 实体
- **Link**：`part_of`（children 嵌套）/ `provides_capability`（part.capabilities）/ `has_part`（顶层 parts）/ `constrains`（part.constraints）
- **绑定 Action**：蓝图 `actions:` 声明的动作绑定到内建 handler，产出 ActionRegistry

生成的实体走 **Gate A（SHACL）** 校验，非法蓝图直接拒绝。

## 运行

```bash
.venv/Scripts/python.exe cli.py hardware-build --file hardware/ti5.yaml
# 或程序化：
#   from eo.hardware import build_from_blueprint, load_blueprint
#   crud, registry = build_from_blueprint(load_blueprint("hardware/ti5.yaml"))
```

## 蓝图格式要点

| 段 | 语义 |
|---|---|
| `robot` | 台账（id/serial/model/status）|
| `capabilities` | 能力注册表（部件 capabilities 引用 code）|
| `parts` | 部件树：`children` 嵌套 = part_of；`capabilities` = provides_capability；`constraints` = constrains |
| `actions` | 绑定 Action：`handler` 引用内建动作，`params/targets/target_param` 决定绑定校验 |

部件 id 按树路径生成：`eo:part/<robot_id>/<路径>`（如 `eo:part/ti5/arm/wrist`）。

## 边界

- 硬件蓝图只生成**硬件本体**（机器人/部件/能力/约束）；任务/物体/故障事件/测点等运行时内容不在此列。
- `constraints` 的 `expression` 必填（对应 Schema Constraint.expression required）。
