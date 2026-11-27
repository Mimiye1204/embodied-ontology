# DDL 迁移约定（TimescaleDB / Neo4j）

> 给时序库与图库 DDL 加版本与迁移约定，把这两份契约「锁死」。
> 关联 docs/01 §7（Schema 迁移安全表）、docs/02 §6（三库类型映射）。

## 1. 目录与权威性

```
ddl/
├── migrations/              ← 唯一权威（增量变更只加这里）
│   ├── timescale/0001_init.sql
│   └── neo4j/0001_init.cypher
├── MIGRATIONS.md            ← 本文档
├── timescale_schema.sql     ← 当前完整快照（fresh install 直接用）
└── neo4j_schema.cypher      ← 当前完整快照（fresh install 直接用）
```

- **migrations/ 是权威**：按版本号升序执行，已执行的迁移**绝不修改**。
- **快照文件是派生物**：每次新增迁移后，把快照同步到「最新完整状态」，供新环境一次性建库。

## 2. 版本登记

| 存储 | 登记机制 |
|---|---|
| TimescaleDB | `schema_migrations` 表（version PK + description + applied_at） |
| Neo4j | `:SchemaMigration` 节点（version + description + applied_at） |

应用迁移时把版本写入登记，重复执行幂等（SQL 用 `ON CONFLICT DO NOTHING` / `IF NOT EXISTS`；Cypher 用 `IF NOT EXISTS` / `MERGE`）。

## 3. 加一条迁移的标准动作

1. 新建 `migrations/timescale/0002_<描述>.sql` 或 `migrations/neo4j/0002_<描述>.cypher`
2. 版本号递增，内容幂等
3. 写入版本登记（`schema_migrations` / `:SchemaMigration`）
4. 同步对应快照文件（`timescale_schema.sql` / `neo4j_schema.cypher`）
5. 若改动与 Schema 相关，同步 `schema/embodied_ontology.yaml` 的版本号

## 4. 迁移安全表（对齐 docs/01 §7）

| 变更 | 安全性 | 要求 |
|---|---|---|
| 加表 / 加列（可空）/ 加索引 | 安全 | 新迁移 + 快照同步 |
| 加唯一约束 | 需回填 | 先查重再建约束 |
| 改列类型 / 删列 / 删表 | 破坏性 | 先在本体层 `deprecated` 一个版本，再迁移 |
| 加 hypertable 保留策略 | 安全 | `add_retention_policy` |
