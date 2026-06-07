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

# 当前系统未正式上线：不要新增增量 revision。
# 如需调整 schema，直接修改 ORM，并更新 0001_baseline_orm_metadata。
```

## 初始基线

`0001_baseline_orm_metadata` 在 `upgrade` 中调用 `Base.metadata.create_all()`，用于：

- 全新空库一次性建表。
- 预上线阶段把所有 schema 调整归一到这个初始版本。

正式上线前不维护历史兼容迁移，也不保留启动后的轻量补迁移；一致性与数据初始化由业务逻辑保证。

## Docker / CI

镜像与 CI 已包含 `alembic.ini` 与 `alembic/` 目录；确保镜像构建上下文复制了这些文件（见 `Dockerfile`）。
