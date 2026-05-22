# 数据库结构迁移（Alembic）

本项目使用 [Alembic](https://alembic.sqlalchemy.org/) 管理 PostgreSQL 表结构变更。应用启动时（`DatabaseManager` 初始化）会执行 `alembic upgrade head`，与手动在部署流水线中执行等价。

## 前置条件

- 已设置 `DATABASE_URL`（`postgresql://` 或 `postgresql+psycopg2://`）。
- 在**仓库根目录**运行 CLI（以便找到 `alembic.ini`）。

## 常用命令

在项目根目录执行（若使用 `uv`：`uv run alembic …`）：

```bash
# 查看当前数据库版本
alembic current

# 升级到最新
alembic upgrade head

# 生成空 revision（手写 DDL）
alembic revision -m "add_xyz_column"

# 根据 ORM 与数据库差异自动生成（需能连上目标库）
alembic revision --autogenerate -m "describe_change"
```

生成后务必**人工检查** `alembic/versions/` 下的脚本（索引、重命名、数据回填等 autogenerate 常不完美）。

## 初始基线

`0001_baseline_orm_metadata` 在 `upgrade` 中调用 `Base.metadata.create_all()`，用于：

- 全新空库一次性建表；
- 已有与 ORM 一致的库：对已存在的表基本为 no-op，并写入 `alembic_version` 以便后续增量迁移。

后续变更请新增 revision，**避免**再依赖 `create_all` 作为长期方案。

## 与 `src/db_schema.py` 的关系

`run_user_scoped_migrations` 仍可在启动后做少量**数据/兼容**修正（例如历史行的 `user_id` 回填）。**新增列、改约束**等结构性变更应优先放在 Alembic revision 中，便于审计与回滚。

## Docker / CI

镜像与 CI 已包含 `alembic.ini` 与 `alembic/` 目录；确保镜像构建上下文复制了这些文件（见 `Dockerfile`）。
