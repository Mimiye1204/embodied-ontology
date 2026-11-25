# 具身本体论 · 仿真项目（sim/）

在无真实机器人的情况下，用本体引擎完整跑通「调度 → 拦截 → 执行 → 故障 → 写回」闭环。
所有决策（可达性/拦截/故障传播/校验）都走 `eo` 引擎真实代码，仿真只负责：
造时序数据、触发场景事件、维护任务生命周期。

## 运行

```bash
.venv/Scripts/python.exe sim/main.py --list                      # 列出场景
.venv/Scripts/python.exe sim/main.py --scenario slip_loop        # 跑一个场景（默认）
.venv/Scripts/python.exe sim/main.py --scenario fault_sensor --steps 15
```

产物（sim/outputs/，已 gitignore）：
- `timeline.jsonl` — 事件时间线（每事件一行 JSON）
- `fleet-final.jsonld` — 仿真结束时的本体快照（Gate C 校验后导出）
- `telemetry.db` — 时序数据（SQLite，表结构与生产一致）

## 场景

| 场景 | 演示 |
|---|---|
| `fault_sensor` | 注入「六维力传感器失效」模式 → 故障事件入图 → 传播 → 抓鸡蛋不可达、端杯子不受影响 → 根因回溯 |
| `dispatch_intercept` | 下发「推箱子」→ 三维拦截（力矩/负载/抓握力）→ 改写建议 |
| `slip_loop` | 力读数异常剖面（12N→4N）→ 滑移检测 → 写回 surface=slippery（Gate A 校验通过）→ 规则重跑 → 拦截建议力度×1.5 |

## 写场景

继承 `eosim.scenarios.base.Scenario`，实现 `setup(env)` / `tick(env, t)`，
在 `eosim/scenarios/__init__.py` 注册。可用的仿真原语（全部走真实引擎逻辑）：

```python
env.write(entities, t)          # 写回（Gate A：合并后 SHACL 校验，拒绝则不进图）
env.dispatch(task_id, t)        # 下发任务（Gate B：可达性写回 + 拦截改写 + ActionLog）
env.inject_fault(mode_id, t)    # 注入故障（按 FaultMode 建事件 + 传播 + ActionLog）
env.runtime.set_anomaly(...)    # 时序异常剖面
env.timeline.event(t, src, msg) # 时间线事件
```

## 扩展方向

- 真实遥测回放：`RobotRuntime.tick` 换成读 TimescaleDB/CSV 数据源
- 多任务并发调度：`TaskDispatcher` 加队列/优先级（Task.priority 已在 Schema）
- 闭环重规划：拦截 → 改写 → 重新下发（`dispatch` 返回的改写建议接规划器）
- 接机器人端：仿真产物（任务/约束/模式）经 JSON-LD 下发真机
