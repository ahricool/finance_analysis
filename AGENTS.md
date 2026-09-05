# Finance Analysis 仓库指南

本文件面向修改本仓库的 coding agent。内容以当前源码为准；更细的子目录规则见：

- 后端：`src/finance_analysis/AGENTS.md` <!-- pragma: allowlist secret -->
- WebUI：`web/AGENTS.md`
- 隔离 Qlib Worker：`qlib_worker/AGENTS.md`

现有 `README.md` 主要是 reference data / daily sync 升级运维备忘，不是完整快速开始。
专题细节见 `docs/market-streamer.md`、`docs/quant-research.md` 和
`docs/etf-rotation.md`；其中时间表和迁移步骤可能落后，易变事实仍以代码为准。

## 系统概览

Finance Analysis 是一个多市场证券研究与任务自动化系统。Instrument、WatchList 和实时 Streamer 支持 CN/HK/US；定时前复权日线同步与 Quant 只覆盖 CN/US，港股没有独立 daily sync 任务。当前部署不是单体进程，而是以下协作组件：

```text
Vue WebUI ──HTTP/SSE/WS──> FastAPI
                              │
                    PostgreSQL（业务事实源） <!-- pragma: allowlist secret -->
                              │
              Celery Worker <─┴─> Redis <── Celery Beat
                    │                    └── 实时行情 Streamer
                    └── qlib queue ──> Python 3.12 Qlib Worker
```

- FastAPI 提供 Cookie/JWT 会话、REST、SSE 和 WebSocket 接口。
- PostgreSQL 是用户、证券、前复权日线、任务状态、分析历史及策略结果的权威存储。 <!-- pragma: allowlist secret -->
- Redis 是 Celery broker/result backend、Beat 心跳、实时行情状态和量化“最新结果”缓存；不是业务事实源。
- Celery Worker 执行按需及周期任务，Celery Beat 根据代码注册表发任务；没有 APScheduler。
- `finance-analysis-stream` 独立消费 Longbridge 实时行情，把 Quote、1 分钟 K 线、趋势和形态状态写入 Redis，不写 PostgreSQL 行情。 <!-- pragma: allowlist secret -->
- Qlib 0.9.7 只能运行在独立 Python 3.12 Worker；主应用为 Python 3.13。两侧只经 Redis Celery 协议和 `data/quant` 工件交换，不共享数据库凭据。
- WebUI 是 Vue 3 SPA；开发时由 Vite 代理 `/api`，生产由 nginx 同源代理到 FastAPI。

## 技术栈与入口

| 范围 | 技术 | 入口 |
| --- | --- | --- |
| 主应用 | Python 3.13、FastAPI、SQLAlchemy 2、Alembic | `main.py` → `finance_analysis.__main__:main` → `interfaces/api/app.py` | <!-- pragma: allowlist secret -->
| 后台任务 | Celery 5、Redis | `finance_analysis.tasks.celery.app:celery_app` | <!-- pragma: allowlist secret -->
| 周期调度 | Celery Beat、代码定义的 crontab | `tasks/celery/schedule/definitions.py` |
| 实时行情 | asyncio、Longbridge、Redis | `finance-analysis-stream` → `market_stream/__main__.py` |
| 量化 Worker | Python 3.12、Qlib 0.9.7、LightGBM | `qlib_worker.celery_app:celery_app`，仅消费 `qlib` 队列 |
| 前端 | Vue 3、TypeScript、Vite、Pinia、vue-zustand、Tailwind 4 | `web/index.html` → `web/src/main.ts` → `App.vue` |

Python 包使用 `src/` layout。主应用 CLI 来自 `pyproject.toml`：

- `finance-analysis`：FastAPI 服务。
- `finance-analysis-stream`：实时行情常驻服务。

服务地址由 `SERVER_HOST` / `SERVER_PORT` 控制，默认 `0.0.0.0:8000`；健康检查为 `GET /status`，OpenAPI 为 `/docs`。

## 仓库地图

```text
src/finance_analysis/ <!-- pragma: allowlist secret -->
  config/                  `.env` 加载和类型化环境变量解析
  core/                    统一路径、UTC 时间和日志基础设施
  interfaces/api/          FastAPI 工厂、中间件、依赖、v1 endpoints/schemas
  analysis/                个股分析流水线、技术分析、历史加载和报告完整性
  agent/                   工具调用 Agent、skills、策略路由、会话与研究
  integrations/market_data 统一行情门面、Provider 注册/路由/校验、实时状态
  stocks/                  代码/市场规范化、证券查询、前端股票索引
  database/                ORM、仓储、连接、启动迁移和种子数据
  tasks/                   Celery 应用、任务生命周期、队列、周期定义与 jobs
  market_stream/           独立 Longbridge streamer、订阅、预热、趋势/形态
  quant/                   数据集导出、研究特征、信号融合和组合构建
  etf_rotation/            ETF 动量轮动领域模型与服务
  trend_following/         多市场趋势跟踪领域模型与服务
  market_review/           市场复盘、交易日历、运行时配置
  market_intelligence/     美股社交舆情适配
  search/                  多搜索 Provider 及统一搜索服务
  llm/                     LiteLLM 配置、调用、fallback 与模型视图
  reporting/               报告 schema、本地化、Jinja/Markdown/图片渲染
  notification/            路由、降噪及 Telegram/SMTP/ntfy/Webhook/AstrBot
  stock_lists/             CSV/Excel/文本股票代码导入解析
  patches/                 受配置控制的第三方兼容补丁
  users/                   会话 JWT、用户配置和数据归属
qlib_worker/               独立 Python 3.12 Qlib Celery 包及自身锁文件/测试
web/                       Vue SPA、Vitest 与 Playwright
alembic/                   PostgreSQL schema/data migrations <!-- pragma: allowlist secret -->
strategies/                Agent 内置 YAML strategy skills
templates/                 Jinja2 报告模板
tests/                     主应用 pytest；`tests/market_stream/` 为 streamer 测试
docs/                      专题说明；有些说明可能落后，修改前与源码核对
data/                      默认运行时数据根，不是源码
static/                    Web 构建产物，由 `web/vite.config.ts` 生成
```

不要恢复已删除的根级 `api/`、`bot/`、`data_provider/` 或通用 `services/` 目录。领域服务放在自己的包内；ORM 放 `database/models/`，仓储放 `database/repositories/`。

## 关键数据流

### 个股分析

1. Web 调 `POST /api/v1/analysis/analyze`；异步请求由 `tasks/queue.py` 发布 Celery 任务，同步请求直接走 `AnalysisService`。
2. `StockAnalysisPipeline` 要求 PostgreSQL 已有目标前复权日线；普通分析不负责补写历史行情。 <!-- pragma: allowlist secret -->
3. `MarketDataService` 聚合实时 Quote、证券信息及可选基本面；分析还会执行技术指标、新闻搜索和可选社交舆情。
4. 传统 LLM 路径或 Agent 路径生成 `AnalysisResult`。
5. 分析历史、上下文和 LLM 用量写 PostgreSQL；报告经 `reporting/` 渲染，并可由 `notification/` 保存或推送。 <!-- pragma: allowlist secret -->
6. 任务状态始终读 PostgreSQL `task` 记录，不从 Redis 推断。 <!-- pragma: allowlist secret -->

### 市场数据

- 业务代码只应调用 `integrations/market_data/MarketDataService`，不要直接选择 Provider。
- 证券代码在边界处规范为 `ticker.region`，如 `600519.SH`、`AAPL.US`。
- 日线唯一标准是前复权。`db_only`、`db_first`、`db_fresh`、`remote_only` 决定读取策略；远程结果不会由查询接口自动持久化。
- 只有显式维护任务写 `instrument`、`stock_daily` 及 Universe。主数据/指数成分同步与日线同步是分离任务。
- Streamer 的 Redis 实时状态可被分析流水线和 `/api/v1/market-data/ws` 读取；缺失时按 Provider 链降级。

### 周期任务

`tasks/celery/schedule/definitions.py` 是任务名称、时区、crontab、队列和过期时间的唯一代码事实源。Beat 负责发布，普通 Worker 消费 `celery,alerts,analysis,ingestion,maintenance`。任务中心展示代码定义并通过 Beat 心跳判断调度器状态。

### 量化

1. 主应用从 PostgreSQL 固定 Universe 与前复权日线生成不可变 Qlib dataset artifact。 <!-- pragma: allowlist secret -->
2. 主 Worker 把版本化 JSON payload 发布到 `qlib` 队列。
3. Qlib Worker 读取工件，训练或预测后只返回 JSON/工件 URI。
4. 主 Worker 的 callback 完成信号融合、组合构建及 PostgreSQL 持久化；Redis 只缓存最新视图。 <!-- pragma: allowlist secret -->

详细边界见 `docs/quant-research.md`，但调度时间等易变信息应以 `definitions.py` 为准。

## API 导航

所有 `/api/v1/*` 默认由会话中间件保护；认证入口、OpenAPI 与兼容 health 路径的完整豁免表见 `interfaces/api/middlewares/auth.py::EXEMPT_PATHS`。主要路由聚合在 `interfaces/api/v1/router.py`：

- `/auth`：登录、状态、用户资料、密码和通知配置。
- `/analysis`：同步/异步个股分析、市场复盘及兼容任务查询。
- `/agent`：模型/skill 列表、聊天、SSE 流、会话和深度研究。
- `/history`：分析记录、详情、删除和导出。
- `/stocks`：证券静态信息、实时 Quote、日线历史和 CSV/Excel/文本代码解析。
- `/watch-list`：用户级自选股 CRUD。
- `/calendar`：日历记录和财经事件。
- `/tasks`：周期定义、手动触发及任务运行记录。
- `/quant`、`/etf-rotation`、`/trend-following`：研究结果与运行入口。
- `/market-data/ws`：基于 Cookie 的用户自选股实时 WebSocket。
- `/usage`：LLM 使用统计；`/celery` 是演示/诊断端点。

具体请求/响应以对应 `endpoints/` 和 `schemas/` 为准，不要根据前端字段猜测后端契约。

## 配置

复制 `.env.example` 为 `.env`；`ENV_FILE` 可覆盖位置。`load_env()` 使用 `override=False`，已有进程环境变量优先，且配置函数广泛使用 `lru_cache`；测试中修改环境后要清相应 cache。

核心配置组：

- 基础设施：`DATABASE_URL`（只支持 PostgreSQL）、`REDIS_URL`、`DATA_DIR`、`SECRET_KEY`。 <!-- pragma: allowlist secret -->
- 服务/CORS：`SERVER_HOST`、`SERVER_PORT`、`CORS_ORIGINS`、`CORS_ALLOW_ALL`。
- LLM/Agent：`LLM_*`、`AGENT_*`；统一调用在 `llm/`，不要在业务模块直接创建厂商 SDK client。
- 搜索：`ANSPIRE_*`、`BOCHA_*`、`MINIMAX_*`、`TAVILY_*`、`BRAVE_*`、`SERPAPI_*`、`SEARXNG_*`。
- 行情：`TICKFLOW_*`、`LONGBRIDGE_*`、`MARKET_DATA_*`、`REALTIME_REDIS_URL`、`MARKET_STREAM_*`。
- 量化：`QUANT_ARTIFACT_ROOT`、`QUANT_CACHE_TTL_SECONDS`、`QUANT_MIN_UNIVERSE_COVERAGE`。
- 通知：`TELEGRAM_*`、`EMAIL_*`、`NTFY_*`、`CUSTOM_WEBHOOK_*`、`ASTRBOT_*`。

以各领域 `config.py` 与 `.env.example` 为准。不要提交 `.env`、token、数据库密码或真实通知地址。

路径统一从 `core/paths.py` 获取。默认 `DATA_DIR=<repo>/data`，包含日志、报告、上传、缓存、临时文件和量化工件；测试使用临时目录或路径 helper，不要 mock `__file__`。

## 安装与运行

要求：Python 3.13、`uv`；Web 以 `package.json` 声明的 `pnpm@11.1.3` 为准。完整本地运行还需要 PostgreSQL 16 和 Redis 7。 <!-- pragma: allowlist secret -->

```bash
uv sync
cp .env.example .env               # 填写本地连接与可选外部服务
uv run alembic upgrade head
uv run python main.py              # FastAPI :8000
uv run finance-analysis-stream     # 可选：独立实时行情

cd web
pnpm install --frozen-lockfile
pnpm run dev                       # Vite :5173
```

全栈开发：

```bash
docker compose -f docker-compose.dev.yml up --build
# docker-compose.yml 默认 include 开发配置
```

开发 Compose 会启动 PostgreSQL、Redis、server、web、普通 worker、beat、qlib-worker 和 streamer。生产使用： <!-- pragma: allowlist secret -->

```bash
docker compose -f docker-compose.prod.yml up -d
```

开发及生产 Compose 都通过 nginx Web 容器对外映射 `:8000`；这不是 Vite dev server。只有原生前后端分离开发使用 Vite `:5173`。`docker/nginx.conf` 处理 SPA、API、SSE 和 WebSocket 代理。

### Cursor Cloud

Cloud VM 原生运行 PostgreSQL/Redis，不使用 Docker。若服务未启动，可运行 <!-- pragma: allowlist secret -->
`sudo pg_ctlcluster 16 main start` 和
`sudo redis-server /etc/redis/redis.conf --daemonize yes`。

Cloud 注入的 `DATABASE_URL`/`REDIS_URL` 可能仍含 Compose 主机名或未展开的端口变量。由于 `load_env()` 不覆盖已有环境，启动服务或测试时应在同一命令显式导出指向 `localhost:5432` 的 PostgreSQL URL 与 `redis://localhost:6379/0`，不要依赖 `.env` 覆盖。当前空库会由 `alembic/env.py` 自动创建 metadata 并 stamp head，不再需要旧文档中的 baseline/stamp 手工绕过。 <!-- pragma: allowlist secret -->

Cloud 注入 `LLM_MODEL`/`LLM_API_KEY`/`LLM_BASE_URL` 时，会改变“未配置 LLM”测试的前置条件。运行完整后端门禁时按需用：

```bash
env -u LLM_MODEL -u LLM_API_KEY -u LLM_BASE_URL uv run ./scripts/ci_gate.sh
```

### 数据库迁移

- 应用首次构造 `DatabaseManager` 时自动运行 `alembic upgrade head`，然后初始化默认管理员及量化参考数据。
- 当前 `alembic/env.py` 会对真正空库直接创建当前 ORM metadata 并 stamp 单一 head；已有库正常执行迁移链。
- 当前仓库存在直到 `0042_merge_reference_heads` 的历史迁移。不要按 `docs/MIGRATIONS.md` 中“只改 baseline、不新增 revision”的旧说明操作。
- schema 变更必须同时更新 ORM、Alembic revision 和迁移测试；不要用运行时 `create_all()` 代替已有库迁移。

## 测试与质量检查

后端完整离线门禁：

```bash
uv run ./scripts/ci_gate.sh
```

分阶段运行：

```bash
uv run ./scripts/ci_gate.sh syntax
uv run ./scripts/ci_gate.sh flake8
uv run ./scripts/ci_gate.sh deterministic
uv run ./scripts/ci_gate.sh offline-tests
```

也可运行聚焦测试：

```bash
uv run pytest tests/test_<area>.py -q
uv run pytest tests/market_stream -q
```

只有显式 `@pytest.mark.network` 用例可访问网络；默认测试必须确定、离线。涉及 PostgreSQL 的测试应使用测试库，不要指向开发/生产库。 <!-- pragma: allowlist secret -->

Qlib Worker 使用独立环境：

```bash
uv sync --project qlib_worker
uv run --project qlib_worker pytest qlib_worker/tests -q
```

Qlib Worker 测试当前不在根 `scripts/ci_gate.sh` 或 PR workflow 中，修改该目录时必须单独执行。

Web：

```bash
cd web
pnpm run build
pnpm run lint
pnpm run test
pnpm run test:smoke
```

文档-only 变更至少检查 Markdown 路径、命令与源码一致，并执行适用的快速门禁；不要为文档变更生成或提交 `static/`。

## 代码约定

- Python：4 空格、`snake_case` 函数/模块、`PascalCase` 类、`UPPER_SNAKE_CASE` 常量，行宽 120；Black/isort 配置在 `pyproject.toml`。
- 时间：持久化及跨服务值使用 aware UTC；市场日历和调度必须显式使用对应市场时区，复用 `core/time.py` 与 `market_review/trading_calendar.py`。
- 用户数据：API 通过 `request.state.uid`/依赖注入做用户隔离；仓储调用必须传递 `uid`，管理员端点用 `require_admin`。
- 数据库：写操作应有明确事务边界；新增表/列必须走 Alembic。
- 外部服务：通过现有领域门面接入，保留降级、超时、Provider 错误和离线测试能力。
- Celery：新增周期任务时同步更新 job package、任务注册、schedule definition、queue route、生命周期元数据和测试。
- YAML strategy skill：修改 `strategies/*.yaml` 时同步核对 `strategies/README.md`、skill loader 及 Agent API。
- 生成内容：不要手改 `static/`、量化 artifact、运行日志或 `data/` 下产物。

## 常见改动去向

| 需求 | 首选位置 |
| --- | --- |
| 新 REST/WS 接口 | `interfaces/api/v1/endpoints/` + `schemas/` + `router.py` |
| 新领域逻辑 | 对应领域包的 service/纯函数；endpoint 只做边界处理 |
| 新 ORM/查询 | `database/models/` + `database/repositories/` + Alembic |
| 新行情来源/能力 | `integrations/market_data/providers/` + registry/router/validator |
| 新异步任务 | `tasks/celery/jobs/<job>/` + 注册/路由/生命周期 |
| 新周期任务 | 上述位置 + `tasks/celery/schedule/definitions.py` |
| 新通知渠道 | `notification/senders/` + config/routing/diagnostics |
| 新 LLM 行为 | `llm/` 或 `agent/`，保持统一 client |
| 新前端功能 | 见 `web/AGENTS.md` |
| 新 Qlib 模型/协议 | 见 `qlib_worker/AGENTS.md`，同时核对主应用 quant 边界 |

## 提交前检查

1. 改动是否放在正确领域，未恢复 legacy 目录。
2. API、任务、数据库、前端类型与用户归属是否同步。
3. 是否误把远程查询变成数据库写入，或绕过 `MarketDataService`。
4. 是否保持普通 Worker 与 Qlib Worker 的 Python/队列/凭据隔离。
5. `.env.example`、专题文档、AGENTS 指南是否需要随行为更新。
6. 聚焦测试及相应门禁是否实际通过。
7. 未提交 secret、日志、缓存、Playwright 报告、`node_modules` 或生成的 `static/`。
