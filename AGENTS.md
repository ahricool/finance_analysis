# Finance Analysis 仓库指南

本文件面向修改本仓库的 coding agent。内容以当前源码为准；更细的子目录规则见：

- 后端：`src/finance_analysis/AGENTS.md` <!-- pragma: allowlist secret -->
- WebUI：`web/AGENTS.md`
- 隔离 Qlib Worker：`qlib_worker/AGENTS.md`

现有 `README.md` 主要是 reference data / daily sync 升级运维备忘，不是完整快速开始。
专题细节见 `docs/market-streamer.md`、`docs/quant-research.md`、
专题细节见 `docs/market-streamer.md`、`docs/quant-research.md`、
`docs/etf-rotation.md` 和 `docs/holdings-portfolio-risk.md`；其中时间表和迁移步骤可能落后，易变事实仍以代码为准。

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
- PostgreSQL 是用户、证券、前复权日线、任务状态及策略结果的权威存储。 <!-- pragma: allowlist secret -->
- Redis 是 Celery broker/result backend、Beat 心跳、实时行情状态和量化“最新结果”缓存；不是业务事实源。
- Celery Worker 执行按需及周期任务，Celery Beat 根据代码注册表发任务；没有 APScheduler。
- `finance-analysis-stream` 对自选与持仓并集采集 US/HK Longbridge 推送及 CN 扶摇报价与新浪→腾讯原生分钟线，把 Quote、1 分钟 K 线、趋势和形态状态写入 Redis，不写 PostgreSQL 行情。 <!-- pragma: allowlist secret -->
- Qlib 0.9.7 只能运行在独立 Python 3.12 Worker；主应用为 Python 3.13。两侧只经 Redis Celery 协议和 `data/quant` 工件交换，不共享数据库凭据。
- WebUI 是 Vue 3 SPA；开发时由 Vite 代理 `/api`，生产由 nginx 同源代理到 FastAPI。

## Production Debugging Context

When investigating production issues, assume:

- Production project directory: `~/svr/finance_analysis`
- Production deployment command: `bash deploy.sh`

生产发布先拉取同一提交的 SHA 镜像并固定 digest，暂停 Beat 后无限等待普通/Qlib worker
优雅退出，再迁移和替换应用，健康检查通过后恢复 Beat；不更新 PostgreSQL/Redis。
不持久化 Beat 调度状态，不补发部署期间漏掉的定时任务。失败后修复并重新运行 `bash deploy.sh`，
会准备最新 main 并重新等待当前 worker；pending 只供诊断，不锁定旧 SHA/digest。
`--resume` 是正常部署的兼容别名，不再提供恢复旧容器的 `--recover`。详见 `docs/deployment.md`。

These are operational facts for debugging and incident investigation.
Use them when checking deployment state, logs, runtime files, migrations, or service behavior.


## 技术栈与入口

| 范围 | 技术 | 入口 |
| --- | --- | --- |
| 主应用 | Python 3.13、FastAPI、SQLAlchemy 2、Alembic | `main.py` → `finance_analysis.__main__:main` → `interfaces/api/app.py` | <!-- pragma: allowlist secret -->
| 后台任务 | Celery 5、Redis | `finance_analysis.tasks.celery.app:celery_app` | <!-- pragma: allowlist secret -->
| 周期调度 | Celery Beat、代码定义的 crontab | `tasks/celery/schedule/definitions.py` |
| 实时行情 | asyncio、Longbridge、Redis | `finance-analysis-stream` → `market_stream/__main__.py` |
| 量化 Worker | Python 3.12、Qlib 0.9.7、LightGBM | `qlib_worker.celery_app:celery_app`，仅消费 `qlib` 队列 |
| 前端 | Vue 3、TypeScript、Vite、Pinia、Tailwind 4 | `web/index.html` → `web/src/main.ts` → `App.vue` |

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
  integrations/market_data 统一行情门面、Provider 注册/路由/校验、实时状态
  stocks/                  代码/市场规范化、证券查询、前端股票索引
  database/                ORM、仓储、连接、启动迁移和种子数据
  tasks/                   Celery 应用、任务生命周期、队列、周期定义与 jobs
  market_stream/           独立 Longbridge streamer、订阅、预热、趋势/形态
 quant/                   Qlib 数据集导出、市场状态、信号融合和目标组合构建
  etf_rotation/            ETF 动量轮动领域模型与服务
  trend_following/         多市场趋势跟踪领域模型与服务
  market_review/           市场复盘、交易日历、运行时配置
  holdings_review/         双市场私有持仓复盘、冻结输入与结构化LLM建议
  llm/                     API / SSH CLI 调用、重试、审计日志与用量统计
  reporting/               报告语言配置与 Markdown 图片转换
  notification/            路由、降噪及 Telegram/ntfy 与消息持久化
  patches/                 受配置控制的第三方兼容补丁
  users/                   会话 JWT、用户配置和数据归属
qlib_worker/               独立 Python 3.12 Qlib Celery 包及自身锁文件/测试
web/                       Vue SPA、Vitest 与 Playwright
alembic/                   PostgreSQL schema/data migrations <!-- pragma: allowlist secret -->
tests/                     主应用 pytest；`tests/market_stream/` 为 streamer 测试
docs/                      专题说明；有些说明可能落后，修改前与源码核对
data/                      默认运行时数据根，不是源码
static/                    Web 构建产物，由 `web/vite.config.ts` 生成
```

不要恢复已删除的根级 `api/`、`bot/`、`data_provider/` 或通用 `services/` 目录。领域服务放在自己的包内；ORM 放 `database/models/`，仓储放 `database/repositories/`。

## 关键数据流

### 个股分析已退役

个股决策仪表盘、单股分析入口、美股盘前分析任务及其 Prompt/pipeline 已删除。
旧手动大盘复盘和盘前新闻抓取分析也已删除；定时美股收盘复盘、持仓复核继续独立运行。
新闻退役迁移 `0086_retire_news` 删除新闻原文/关联/判断、任务历史及通知；时间线只保留宏观与财报。见 `docs/news-removal.md`。
迁移 `0084_drop_stock_analysis_archive` 删除历史分析和基本面快照表及其全部数据；依赖迁移和残留清单见 `docs/stock-analysis-removal.md`。

### 市场数据

- 业务代码只应调用 `integrations/market_data/MarketDataService`，不要直接选择 Provider。
- 证券代码在边界处规范为 `ticker.region`，如 `600519.SH`、`AAPL.US`。
- 日线唯一标准是前复权。`db_only`、`db_first`、`db_fresh`、`remote_only` 决定读取策略；远程结果不会由查询接口自动持久化。
- 只有显式维护任务写 `instrument`、`stock_daily` 及 Universe。主数据/指数成分同步与日线同步是分离任务。
- `database/core_index_etf.py` 为CN/US核心指数ETF维护直接日线同步成员，不扩大ETF/Trend策略池；
  迁移`0077_core_index_etf_sync`，见`docs/core-index-etf-sync.md`。
- Streamer 的 Redis 实时状态供 `/api/v1/market-data/ws`、SSE 与持仓行情使用。

### 周期任务

`tasks/celery/schedule/definitions.py` 是任务名称、时区、crontab、队列和过期时间的唯一代码事实源。Beat 负责发布，普通 Worker 消费 `celery,alerts,analysis,ingestion,maintenance`。任务中心展示代码定义并通过 Beat 心跳判断调度器状态。

### 量化

1. 主应用从 PostgreSQL 固定 Universe 与前复权日线；训练生成可复用不可变工件，每日推理生成任务级临时 Qlib 输入。 <!-- pragma: allowlist secret -->
2. 主 Worker 把版本化 JSON payload 发布到 `qlib` 队列。
3. Qlib Worker 读取工件，训练或预测后只返回 JSON/工件 URI。
4. 主 Worker 的 callback 完成信号融合、组合构建及 PostgreSQL 持久化；Redis 只缓存最新视图。 <!-- pragma: allowlist secret -->

Quant 0081：每日推理输入为任务级临时工件，不再创建 dataset 记录；训练输入按实验复用。
双模型成组发布/回滚，正式结果原子写入；临时输入成功后清理，失败保留24h，维护任务受心跳/文件锁保护。
前端移除数据集页，模型管理仅管理员可见。

详细边界见 `docs/quant-research.md`，但调度时间等易变信息应以 `definitions.py` 为准。

## API 导航

所有 `/api/v1/*` 默认由会话中间件保护；认证入口、OpenAPI 与兼容 health 路径的完整豁免表见 `interfaces/api/middlewares/auth.py::EXEMPT_PATHS`。主要路由聚合在 `interfaces/api/v1/router.py`：

- `/auth`：登录、状态、用户资料、密码和通知配置。
- `/stocks`：证券静态信息、实时 Quote、日线历史和证券主数据搜索。
- `/watch-list`：用户级自选股 CRUD 与跨市场用户标签；列表及实时接口按市场/分组筛选，标签不影响后台任务范围。见 `docs/watch-list.md`。
- `/calendar`：日历记录和财经事件。
- `/tasks`：周期定义、手动触发及任务运行记录。
- `/quant`、`/etf-rotation`、`/trend-following`：研究结果与运行入口；趋势预演为 `GET /trend-following/preview`。
- `/holdings`：DB 持仓买卖/现金、操作记录与日 K 买卖标记；页面 `/market/holdings`。
- `/holdings-review`：本人双市场持仓复盘与日期历史，只读冻结结果；页面 `/market/holdings-review`。
- `/market-data/ws`、`/market-data/events`：用户自选股/持仓行情 WS 与 HTTP SSE；`scope=holdings&market=CN|US` 为持仓。WS连续两次失败固定回落SSE。
- `/usage`：LLM 使用统计；`/celery` 是演示/诊断端点。

具体请求/响应以对应 `endpoints/` 和 `schemas/` 为准，不要根据前端字段猜测后端契约。

## 配置

复制 `.env.example` 为 `.env`；`ENV_FILE` 可覆盖位置。`load_env()` 使用 `override=False`，已有进程环境变量优先，且配置函数广泛使用 `lru_cache`；测试中修改环境后要清相应 cache。

核心配置组：

- 基础设施：`DATABASE_URL`（只支持 PostgreSQL）、`REDIS_URL`、`DATA_DIR`、`SECRET_KEY`。 <!-- pragma: allowlist secret -->
- 服务/CORS：`SERVER_HOST`、`SERVER_PORT`、`CORS_ORIGINS`、`CORS_ALLOW_ALL`。
- LLM：`LLM_*`；统一调用在 `llm/`，不要在业务模块直接创建厂商 SDK client。
- 行情：`TICKFLOW_*`、`LONGBRIDGE_*`、`MARKET_DATA_*`、`REALTIME_REDIS_URL`、`MARKET_STREAM_*`。
- 量化：`QUANT_ARTIFACT_ROOT`、`QUANT_MIN_UNIVERSE_COVERAGE`。
- 通知：`TELEGRAM_*`、`NTFY_*`。

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
- 生成内容：不要手改 `static/`、量化 artifact、运行日志或 `data/` 下产物。
- 前端表格：所有数据列表头支持点击排序；先排序再前端分页，空值始终靠后。真正后端分页与操作列例外，详见 `web/AGENTS.md` 的“表格排序”。

## 常见改动去向

| 需求 | 首选位置 |
| --- | --- |
| 新 REST/WS 接口 | `interfaces/api/v1/endpoints/` + `schemas/` + `router.py` |
| 新领域逻辑 | 对应领域包的 service/纯函数；endpoint 只做边界处理 |
| 新 ORM/查询 | `database/models/` + `database/repositories/` + Alembic |
| 新行情来源/能力 | `integrations/market_data/providers/` + registry/router/validator |
| 新异步任务 | `tasks/celery/jobs/<job>/` + 注册/路由/生命周期 |
| 新周期任务 | 上述位置 + `tasks/celery/schedule/definitions.py` |
| 新 LLM 调用 | `llm/`，保持 API / SSH CLI 二选一；配置见 `docs/llm.md` |
| 新通知渠道 | `notification/senders/` + config/routing/diagnostics |
| 新前端功能 | 见 `web/AGENTS.md` |
| 新 Qlib 模型/协议 | 见 `qlib_worker/AGENTS.md`，同时核对主应用 quant 边界 |
| DB 持仓 | `portfolio/` |

## 提交前检查

1. 改动是否放在正确领域，未恢复 legacy 目录。
2. API、任务、数据库、前端类型与用户归属是否同步。
3. 是否误把远程查询变成数据库写入，或绕过 `MarketDataService`。
4. 是否保持普通 Worker 与 Qlib Worker 的 Python/队列/凭据隔离。
5. `.env.example`、专题文档、AGENTS 指南是否需要随行为更新。
6. 聚焦测试及相应门禁是否实际通过。
7. 未提交 secret、日志、缓存、Playwright 报告、`node_modules` 或生成的 `static/`。

## BTC V0.1

`crypto/` 仅负责 BTCUSDT 策略；`integrations/crypto/binance.py` 是薄公共 REST client，不接股票 Provider 链。
页面行情由浏览器直接访问 Binance REST / 单一 WS（八档周期），策略通过后端 REST 独立读取。
Beat `crypto_btc_strategy` 每 15m 收盘后读取原生 15m/1h 闭合线，只保存策略状态与快照；不保存行情，不使用行情 Redis 或后端 WS。
已有快照按15m逐根补算；仓位为position_pct（0–1），仓位变化保存在snapshot，绩效从完整快照动态计算。
详见 `docs/crypto-btc.md`；测试位于 `tests/crypto/`。


BTC 多策略以 `strategy_key + symbol` 隔离，代码注册表当前仅 `btc_breakout_v1`。共享 Binance REST 窗口、独立 catch-up 与状态行锁；仓位变化保存于 snapshot，绩效/CAGR/负值回撤动态派生，selector 不影响行情连接。详见 `docs/crypto-btc.md`。

## 消息边界

所有系统消息先写 `notification`（`uid` 非空为用户消息，空为全局消息），再执行现有 Noise Control 和 Telegram/ntfy 推送；不保存 delivery 状态。读取仅限本人 + 全局。报告不再写 Timeline 或本地文件；Calendar 只保存 earnings/macro 真实事件。详见 `docs/notifications.md`。

## Market Structure / Trend Health

`market_structure/` 独立计算 CN/US 收盘市场结构，任务 `market_structure_cn/us` 分别在当地 18:50 / 21:50 读取已存 ETF Ranking 与 DB 日线；API `/api/v1/market-structure` 只读 PostgreSQL snapshot。手动回填复用 `/market-structure/run` 的日期范围任务。Trend lifecycle/fragility 集成现有正式/preview 计算链，分别保存正式/Preview PostgreSQL 表，不改交易规则。范围、公式、缺失数据语义见 `docs/market-structure.md`。

## 信息输入边界

个股决策分析和旧手动大盘复盘已退役；定时美股收盘复盘只读取自身结构化行情数据，不读取新闻。
系统不负责通用互联网检索；`holdings_review/`允许通过LLMClient核查已有持仓、主要指数和相关板块的公告/事件，并保存transport证据；`signal_center/`另允许通过LLMClient联网核查候选的公告/事件/风险并保存检索证据，见`docs/signal-center.md`。`earnings_outlook/` 是财报研究例外，仅对 Nasdaq-100 当前有效股票成员
通过 LLMClient 执行有传输证据的搜索；不改变其他模块边界，详见 `docs/investment-timeline.md`。通用新闻采集与分析已退役；Longbridge仍用于行情和财经日历。宏观与财报事件/研究继续运行，见 `docs/investment-timeline.md`。

## Industry Strength

`industry_strength/` 只计算 A 股行业观察，不输出交易动作，与 ETF Rotation 独立。
扶摇是 `integrations/market_data/providers/fuyao.py` 的独立 Provider，通过 `MarketDataService`
复用行业目录、指数历史、当前成分三个 CN capability；`FUYAO_API_KEY` 仅后端读取。
`industry_reference_sync` 每周日上海10:00在 ingestion 队列原子保存 `industry_catalog` / `industry_membership`；首次部署管理员手动同步。
行业正式/Preview 只读已存目录与成分；股票日线批量读 DB，仅缺目标日时远程补取且不落库，Preview 目标为昨日。
扶摇股票历史不支持 batch；Preview 使用全市场分页报价。股票类型批量复用 DB Instrument，不逐股请求 meta。
`industry_strength_cn` 在上海19:10检查收盘、行业/成分覆盖率后保存独立快照；成员观测时间来自周同步，禁止回填历史 Breadth。
个股详情通过只读 classification 显示所属行业。
页面 `/research/industry-strength`，指标和口径见 `docs/industry-strength.md`。

## Holdings

`portfolio/` 是普通股票/ETF 唯一持仓事实源，账户现金、当前持仓、CORE/ADDON lot 和买卖操作写 PostgreSQL。
现金独立设置，买卖不改现金；持仓页面与 Streamer 估值、买卖记录和日 K 标记继续保留。
CN/US Trade Engine 已退役：不再执行盘中机械策略、组合风险计算或市场级 LLM，不生成调仓通知。
迁移 `0087_retire_trade_engine` 删除交易信号、LLM 状态、提醒开关及专属任务/通知/用量历史；见 `docs/holdings-portfolio-risk.md`。

## Market Sentiment

`market_sentiment/` 独立计算 A 股完整盘后涨停池、连板晋级与情绪观察；经现有 FuyaoProvider 四个 CN capability 取数。
`market_sentiment_cn` 上海19:20在独立任务锁下原子保存完整源与结果，核心不完整不覆盖旧结果，补数重算后续派生值。
`/api/v1/market-sentiment` GET只读，管理员 `/run` 支持单日或最多31交易日异步补数；页面 `/research/market-sentiment`。
主观察为非ST且非未开板新股；官方天梯有限样本和补充池独立展示，不参与评分。见 `docs/market-sentiment.md`。

## Admin MCP

`mcp/` 是挂载在现有 FastAPI `/mcp/` 的管理员底层只读诊断入口，独立 Bearer key；MCP DB / Redis URL 是可选 override，默认复用业务连接配置，
可选独立只读账号增强隔离；保留 SQL / Redis 只读限制，禁止新增业务/写入/命令执行 tool。
文件 jail 固定 `/data`，生产 server 只读挂载现有数据目录。权限、资源限制和部署步骤见
`docs/mcp.md`，离线/临时服务测试位于 `tests/mcp/`。

## Dragon Tiger Flow

`dragon_tiger_flow/` 独立观察 A 股龙虎榜概念净额，页面 `/research/dragon-tiger-flow`。
Beat `dragon_tiger_flow_cn` 上海19:30，经 `MarketDataService` 的 CN `dragon_tiger_board` 能力采集三类扶摇榜单，
原子保存每日 PostgreSQL 批次；GET只读，管理员可异步补最多31交易日。
1日榜默认单日，支持5/10/20日累计，3日榜仅独立截面；概念等分到分、未分类守恒，缺日不填零。
机构与游资独立观察，游资明细是有限样本，不构造互斥资金来源或交易动作。见 `docs/dragon-tiger-flow.md`。

## Signal Confluence

`confluence/` V2只读正式DB结果并执行规则评分，不调用LLM/Provider或重算上游。
主要宏观15/行业ETF20/行业强度15/Trend30，辅助Quant7/期权5/情绪4/龙虎榜4；缺失不入分母，其他指标按比例分摊。
Trend读取同日20/40/60，分别比较趋势/突破/超跌反弹替代路线后聚合。行业ETF复用静态映射并校验当前轮动池，
目标ETF资格以池配置为准，不依赖Instrument类型；目录粗标STOCK不能切断关联。见`docs/industry-etf-mapping.md`。
CN/US当地20:30/23:30共用60分精选门槛，每日各最多10个；同批次最多50行研究排行，非精选eligible/strong均false，
不得作为共振来源进入盘中确认。精选优先，其余按综合分排列；前端每页10行，低于60标注观察，同日重跑替换。
GET只读历史与冻结证据，V1不重算；迁移`0079_confluence_v2`扩计数上限至8。详见`docs/confluence.md`。

Signal Confluence V2.1宏观15%使用`confluence/sector_macro.py`行业适配，整体风险偏好仅作背景；
分类与ETF共用观测截止，未审核/因子覆盖不足留空，不反转银行农业。CN不将美国利率信用当国内政策。
`confluence_v2`历史仍保留统一分；新任务为`confluence_v2_2`，无自动回填或schema变更。见`docs/confluence.md`。

## Intraday Confirmation

`intraday_confirmation/` V2冻结前一交易日Confluence精选（eligible，非strong子集）、Trend20综合前30和ETF轮动综合前5，去重保留全部来源，不再读Quant。
当地09:20/09:25盘前冻结，交易时段每5分钟读取开盘以来完整原生1min；CN腾讯报价+新浪→腾讯分钟降级，US yfinance。
价格60/相对大盘25/Trend10/量能5，Trend与量能仅辅助；全天等权均价不依赖量，移除固定开盘15m门槛。
历史确认和当前观察分开，首次确认基准不可变；快照与版本化评估轨迹同事务保存（迁移0082），V1池不混算。
GET只读及3/5/10D收益保留，详情可读评估轨迹；页面`/research/intraday-confirmation`，见`docs/intraday-confirmation.md`。


## Unified Signal Center

`signal_center/` 主动读取同日正式Trend20前30、Trend40/60各前10、ETF前10（ETF可推荐）、原行业候选与前端可见的完整正式Confluence批次（当前最多10只）。
不直接读Quant候选/明细；共振保持上游整体含义，可能含Quant贡献，禁止把重复底层事实当独立共振。
所有来源合并去重后固定5桶，每桶LLM选0–3，最终从0–15个中选0–3；CN/US每日合计最多6个，宁缺毋滥。
复用LLMClient联网与transport检索证据；BUY结构化引用冻结字段/数值/日期，NO_TRADE有明确原因。
正式结果与全局notification同事务保存，随后复用report路由push_existing。GET只读，逐只使用DB日线计算后续价格表现。
CN20:40–21:50，US23:40至次日00:30每10分钟检查并等待共振，午夜仍归属前交易日。复用analysis队列与advisory lock。
迁移`0080_signal_center_v2`，旧历史与未完成旧任务保持原版本。页面`/research/signal-center`。详见`docs/signal-center.md`。

## Options Intelligence

`options_intelligence/` 独立做美股低频期权异常与风险研究，不预测/下单。`MarketDataService.get_option_chain` →
`integrations/options/`：yfinance 主链，Alpaca 缺失能力回退；合约/OI 日期来自 Alpaca 只读 Trading API。
报价/IV 不跨来源拼接，Indicative 非 NBBO；未知报价时间不实时评分，未知 OI 日期不次日确认。
三个评分独立，历史预热可 N/A；事件初始证据不可变，次日 OI 与事后股票收益放验证字段。
扫描范围为数据库当前有效 `us_nasdaq100` 成分股 + 美股自选股，不含默认六标的/持仓补充池。
Beat `options_intelligence_intraday/daily` 复用 ingestion 与独立任务锁，真实 NYSE 时段检查；intraday 写独立 PostgreSQL preview（纽约午夜过期），daily 写 PostgreSQL，GET 只读相应存储。
API/页面支持 preview/official 与正式日期选择；正式读取关联日度基线，不回退旧日期或重算历史报价时效。看跌保护初始规则与采集报价流动性研究代理均标注低可信度，不伪装历史分位数或实时 NBBO。
页面 `/research/options-intelligence` 与现有美股股票详情「期权」Tab。迁移 `0070_options_intelligence`；
规则、数据能力、OPRA 检查与配置见 `docs/options-intelligence.md`，离线测试 `tests/options_intelligence/`。

Streamer 页面行情只读 Redis；CN/US 共用日内方向状态，分钟线与形态事件仅保留最近交易日，CN原生1min为新浪→腾讯（免费，单一fallback），报价仍为扶摇，跨周末/长假 TTL 由交易日历确定。自选与持仓表点行展开分钟图、点名称打开详情。ETF扶摇批量参数已实测不支持，保留单证券接口。见 `docs/market-streamer.md`。
个股详情日 K 独立于 Streamer 采集池：后端按需请求该股当天报价生成临时日 K，与多日历史按交易日期去重拼接返回，不写数据库或 Redis。自选股／投资组合实时表格和展开分钟图继续只读 Streamer 缓存。

## Market Heatmap

`market_heatmap/` 在 ingestion 队列每15分钟刷新 CN easyquotation / US yfinance 快照，GET仅读Redis。
页面 `/market/heatmap`，小市值过滤、0.75次幂市值权重与阅读尺寸下限，按行业纵向展示；行业单一归属避免重复。
美股 Yahoo sector/industry 由现有 `reference_data_sync` 周同步保存到 `instrument.metadata.classification`，
行情刷新不采集行业、不写日线。口径、首次初始化与失败保留见 `docs/market-heatmap.md`。

## Stock Strategies

`stock_strategies/` 是共享股票/ETF研究模拟，独立于真实portfolio。十个策略族按原生CN/US市场注册，
`scheduled.stock_strategies` 单任务在盘后读取DB日线与同日正式Trend/ETF状态，逐策略事务隔离失败。
统一启动日空仓、每账户100万本币、收盘信号/次开盘成交、零费用；每日指标和计划持久化，GET不回算。
首次运行冻结Universe，US广度为标普500成分；细节及适配差异见`docs/stock-strategies.md`。
迁移`0076_stock_strategies`，页面`/strategies`，离线测试`tests/stock_strategies/`。
10/23新增CN趋势质量/市场35退出与US均线市场开关/DD30暂停3交易日；独立观察起点不早于2026-10-23，
只读同日正式Trend20及CN Trend60 Path/趋势条件，不请求外部API。

## Research Preview 存储

Trend、ETF、行业和期权研究 preview 使用独立 `research_preview` / `research_preview_item` 表，只保留各范围最新批次。
事务内范围 DELETE 后替换，不混入正式历史；名称复用 Instrument，共同字段只存一次，GET按需投影。
迁移 `0078_research_preview`，有效期及失败清除语义见 `docs/preview-storage.md`，测试 `tests/research_preview/`。

## Holdings Review

`holdings_review/` 独立于已退役交易引擎，CN14:10、US15:10（提前收盘12:10）按实际收盘前50分钟触发。
按用户扇出，冻结真实持仓、指数20根日K、持仓20根日K/12根5min、精简当日ETF/Trend/行业Preview。
每用户每市场一次业务级LLM请求，允许联网并返回结构化HOLD/BUY/REDUCE/SELL/WATCH；BUY只为已有持仓加仓。
uid+market advisory lock，结果与本人notification同事务保存，每天每市场一份Markdown；个人收件地址隔离，默认管理员可用全局地址。
GET本人历史不重算，默认今日或上一交易日；手动触发仅当前复盘窗口。迁移0088，页面“市场→投资组合”下方。
缺失/过期输入明确降级，不传复杂研究诊断或全市场逐股快照，不恢复旧analysis/trade_engine。详见`docs/holdings-review.md`。
