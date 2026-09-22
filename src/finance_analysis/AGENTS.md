# 后端包指南（`src/finance_analysis/`） <!-- pragma: allowlist secret -->

本文件补充根 `AGENTS.md`，用于修改 Python 主应用。主运行时是 Python 3.13；`qlib_worker/` 不属于本包，也不能作为主应用依赖。

## 分层与依赖方向

推荐调用方向：

```text
interfaces/api + tasks/celery/jobs
                 ↓
       领域 service / pipeline
                 ↓
 database repositories + integrations + llm/notification/reporting
                 ↓
       PostgreSQL / Redis / 外部 API <!-- pragma: allowlist secret -->
```

- `interfaces/` 是传输边界：解析请求、鉴权、选择依赖、序列化响应，不应承载核心计算。
- `tasks/celery/jobs/` 是异步适配层：解析 payload、记录生命周期、调用领域服务。
- 顶层领域包（`analysis`、`quant`、`etf_rotation`、`trend_following`、`market_review`、`portfolio`、`trade_engine`）拥有业务规则。
- `database/repositories/` 封装查询和事务；领域代码不应散落 SQL。
- `integrations/` 封装外部行情；`llm/`、`notification/` 同样是共享基础能力。
- 为避免循环导入和高成本启动，现有代码有意在函数内延迟导入数据库、Provider和任务组件；修改前先确认初始化顺序。

## 启动生命周期

`main.py` 只是兼容 wrapper，实际入口为 `finance_analysis.__main__.main()`： <!-- pragma: allowlist secret -->

1. `load_env()` 从 `ENV_FILE` 或根 `.env` 加载变量，且不覆盖进程已有变量。
2. `ensure_data_directories()` 创建运行目录。
3. 初始化后端日志。
4. Uvicorn 导入 `finance_analysis.interfaces.api.app:app`。 <!-- pragma: allowlist secret -->

`app.py` 的 lifespan 不启动任务调度器。Celery Beat 是唯一周期调度进程。

数据库是惰性初始化的：第一次 `DatabaseManager.get_instance()` 会创建 SQLAlchemy engine，强制连接 session 使用 UTC，执行 `alembic upgrade head`，再创建默认管理员和量化参考数据。它只接受 PostgreSQL URL。 <!-- pragma: allowlist secret -->

注意配置对象通常有 `lru_cache`。测试修改环境变量时，需要清理相关 getter 和 `load_env()`/路径 cache；参考现有 `reset_*`、`cache_clear()` 测试模式。

## API

### 应用装配

- `interfaces/api/app.py`：FastAPI factory、CORS、认证中间件、错误处理和 `GET /status`。
- `interfaces/api/v1/router.py`：统一 `/api/v1` 前缀及 endpoint 注册。
- `interfaces/api/deps.py`：SQLAlchemy Session、`uid`、当前用户和管理员依赖。
- `interfaces/api/v1/schemas/`：Pydantic 请求/响应；新增契约应在这里显式建模。

认证中间件保护全部 `/api/v1/*`，只豁免：

- `/api/v1/auth/lookup`
- `/api/v1/auth/login`
- `/api/v1/auth/status`
- OpenAPI 文档和列出的 health 兼容路径

会话由 `users/auth.py` 解析 JWT Cookie，中间件查询用户并写入 `request.state.uid`。用户级读写使用 `get_effective_uid`/`require_current_user`；管理员操作使用 `require_admin`。不要接受客户端提交的 `uid` 作为数据范围。

### Endpoint 模块

| 模块 | 责任 |
| --- | --- |
| `auth.py` | 登录两阶段流程、状态、资料、密码、通知设置 |
| `stocks.py` | 证券静态信息、实时 Quote、日线历史和证券主数据搜索 |
| `watch_list.py` | 用户自选股 CRUD |
| `calendar.py` | 日历条目和财经事件 |
| `tasks.py` | 代码定义的周期任务、管理员手动运行、任务记录 |
| `quant.py` | 固定市场 Universe 的数据集、模型、信号、组合 |
| `etf_rotation.py` / `trend_following.py` | 领域结果与手动运行 |
| `market_data.py` | Cookie 鉴权的实时行情 WebSocket，以及统一前复权 daily-bars HTTP 查询 |
| `usage.py` | LLM 用量 |
| `celery_demo.py` | Celery 连通性演示，不是业务编排入口 |
| `holdings.py` | DB 持仓买卖/现金与交易提醒开关 |
| `trade_engine.py` | 持仓级 Trade Engine 只读结果与管理员手动运行 |

REST 修改至少核对 endpoint、schema、前端 `web/src/api/` 与 `tests/test_*_api*.py`。WebSocket/SSE 还要核对 nginx buffering/upgrade 与断开清理。

## 个股分析

主链：

```text
Celery
  → AnalysisService / StockAnalysisTaskService
  → StockAnalysisPipeline
  → PostgreSQL 历史 + Redis/Provider 实时状态 <!-- pragma: allowlist secret -->
  → 技术分析 + 基本面
  → StockReportAnalyzer → LLMClient
  → AnalysisHistory + 报告 + 通知
```

关键文件：

- `analysis/service.py`：任务侧分析门面和结果组装。
- `analysis/pipeline.py`：数据编排、降级、上下文、LLM 分支、存储、通知。
- `analysis/history/loader.py`：数据库历史完整性边界。
- `analysis/technical/`：趋势和指标。
- `analysis/stock_report_analyzer.py`：prompt、LLM 调用、报告解析与完整性校验。

历史日线同步已从分析链拆开。`fetch_and_save_stock_data()` 名称为兼容保留，但当前只验证数据库历史，不拉取或保存远程日线。不要在分析请求中恢复隐式写行情。


LLM 调用统一进入 `llm/LLMClient`，由 `LLM_BACKEND=api|cli` 二选一。最多重试三次，退避 2 / 4 / 8 秒，受总时间预算限制，不切换 backend 或模型。配置与部署见 `docs/llm.md`。

## 市场数据边界

`integrations/market_data/service.py::MarketDataService` 是业务代码唯一行情门面。

内部结构：

- `models.py`：统一请求、结果、证券、Quote、Bar 和 capability 类型。
- `normalizer.py` / `codes.py`：代码、市场、Provider payload 规范化。
- `registry.py`：Provider + capability 注册。
- `router.py`：按市场/capability 确定性 fallback。
- `validator.py`：结果进入业务层前校验。
- `providers/`：TickFlow、Fuyao、easyquotation（Preview 与 CN 全市场快照 fallback）、yfinance、Longbridge。
  Fuyao 接口、数据语义与缺失能力见 `docs/market-data-providers.md`（仓库根目录）。
- `realtime_state/`：Streamer 写入的 Redis schema 与同步/异步读取。
- `instrument_sync.py`：证券主数据与指数成分同步辅助。

规则：

- 一个批请求不能混合市场。
- 业务标识使用 canonical `ticker.region`，不要依赖裸代码猜市场。
- 日线只接受/返回前复权；`stock_daily` 是持久化权威数据。
- US 日线维护使用 `MarketDataService(daily_sync=True)`：Alpaca SIP `adjustment=all` 优先，yfinance 降级。
  凭据为 `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`；普通查询和实时路由不变。详见 `docs/market-data-providers.md`。
- `get_daily_bars()` 查询不写库。只有 `tasks/celery/jobs/market_data_sync` 等维护任务能写日线。
- `db_only` 只读数据库；`db_first` 本地有任何历史就使用，否则远程；`db_fresh` 比较最新日期并批量补尾部到内存；`remote_only` 绕过 DB。
- Provider 顺序来自 `integrations/market_data/config.py::provider_order()`，不要在调用方硬编码 fallback。
- Query 返回的远程数据是计算期临时数据；需要持久化时必须进入显式同步任务并保留完整失败语义。

## 数据库

### 组织

- `database/base.py`：Declarative Base 和时间规范化。
- `database/models/`：按领域拆分的 ORM。
- `database/repositories/`：按 aggregate 拆分的持久化 API。
- `database/session.py`：engine/session 单例及少量历史兼容方法。
- `database/bootstrap.py`：迁移、默认管理员、量化参考数据。
- `database/seed.py`：参考数据 seed。
- 根 `alembic/`：schema 和数据迁移。

主要持久化 aggregate：

- 用户、自选股、日历、任务。
- `Instrument`、`StockDaily`、`Universe`/`UniverseInclude`/`UniverseMember`。
- 分析历史、新闻/基本面快照、LLM 用量。
- Quant dataset/model/signal/portfolio。
- ETF Rotation 和 Trend Following 快照。

新查询优先加到对应 repository。跨多写操作使用 `session_scope()` 或明确 commit/rollback；从依赖注入拿到的 Session 由请求结束关闭。所有跨进程时间写 aware UTC。

Alembic：

- 空库由 `alembic/env.py::_bootstrap_empty_database()` 创建当前 metadata 并 stamp 当前唯一 head。
- 非空库执行完整 revision 链；数据迁移仍有意义。
- 当前有双 `0041` 分支，由 `0042_merge_reference_heads` 合并。
- 修改 schema 时新建 revision，并补迁移测试；不要修改已发布 revision 或仅修改 baseline。

## Celery 与任务状态

入口和注册：

- `tasks/celery/app.py`：broker/backend、序列化、routes、Beat schedule 和 signal hooks。
- `tasks/celery/jobs/__init__.py`：显式加载的任务包。
- `tasks/celery/schedule/definitions.py`：所有周期定义。
- `tasks/celery/schedule/constants.py`：job id、queue、expires。
- `tasks/queue.py`：异步分析提交门面，供 Celery 任务与内部调用使用。
- `tasks/lifecycle.py`：TaskRecord 状态与日志生命周期。
- `tasks/service.py`：任务中心查询、Beat 状态、管理员手动运行。

普通队列：

- `celery`：默认任务
- `alerts`：盘中提醒
- `analysis`：分析、回调和研究计算
- `ingestion`：行情/日历/参考数据抓取
- `maintenance`：维护
- `qlib`：只能由隔离 Qlib Worker 消费

任务状态和用户可见结果写 PostgreSQL `task` 表。Redis 的 Celery result 不是任务中心事实源。发布阶段的 signal hook 会创建 pending 记录，worker 侧 tracked task 更新 processing/progress/result/failure；不要绕过两端幂等设计。 <!-- pragma: allowlist secret -->

新增任务检查：

1. `jobs/<name>/tasks.py` 和 package 注册。
2. 稳定 Celery task name 与正确 queue route。
3. on-demand metadata 或 periodic `ScheduledTaskDefinition`。
4. payload 必须 JSON 可序列化，敏感内容不能进入 TaskRecord。
5. 生命周期、重复任务/advisory lock、重试和过期语义。
6. `tests/test_celery_task_structure.py`、`test_celery_schedule.py`、`test_task_lifecycle.py` 等聚焦测试。

## Holdings / Trade Engine

`portfolio/` 是 STOCK/ETF 唯一持仓事实源。`trade_engine/` 是中线持仓决策系统，不是全市场 Scanner，也不是日内交易系统。Strategy 完全无状态；Portfolio Risk 输出事实给 LLM；每个市场每 30 分钟最多一次 Market-level LLM，状态写入 `trade_llm_state`。`trade_engine_enabled=false` 不运行 Strategy，LLM target 必须等于 current，但仍计入 NAV 与风险。详见 `docs/holdings-portfolio-risk.md`。

## 实时行情 Streamer

`market_stream/` 是独立 asyncio 常驻服务，不在 FastAPI lifespan 中运行。

流程：

1. 获取 Redis leader lock，防止多个实例同时写。
2. 从 PostgreSQL 读取全部用户的 CN/HK/US WatchList，经 Longbridge symbol 转换后动态对账订阅；无法转换的条目会跳过并记录日志。 <!-- pragma: allowlist secret -->
3. Longbridge 连接按 symbol generation/connection generation 防旧事件污染。
4. 从 Redis 或 Longbridge 历史预热 1 分钟 Bar；预热期实时事件先缓冲再合并。
5. Quote、确认/预览 K 线、MA 趋势、形态、订阅状态与 heartbeat 写 Redis。
6. API `/market-data/ws` 每 5 秒读取用户自己自选股的快照。

Streamer 不写 `stock_daily`，也不替代日线同步。更改 Redis key/schema 时同时修改 `integrations/market_data/realtime_state/`、API、分析读取和 `tests/market_stream/`；参考 `docs/market-streamer.md`。

## Quant、ETF Rotation 与 Trend Following

### Quant

`quant/` 运行在主应用，负责：

- 从固定 `US`/`CN` Universe 和 PostgreSQL 日线构建 immutable dataset。 <!-- pragma: allowlist secret -->
- 维护 dataset/model run/publication 元数据。
- 计算市场状态及日频流水线所需的临时流动性/风险上下文，不持久化手工特征面板。
- 发布版本化 JSON Qlib 任务。
- 接收结果后做信号融合、最终得分排名、模型目标组合及 PostgreSQL 持久化。 <!-- pragma: allowlist secret -->

Qlib worker 不可访问 PostgreSQL。主 Worker 不同步等待 Qlib，训练通过 link/link_error 回调，日频预测通过单任务 `qlib.daily.predict` 加 finalize/fail 回调。协议改动必须主应用与 `qlib_worker/protocol.py` 同步，并保持 schema version 校验。 <!-- pragma: allowlist secret -->

### ETF Rotation


盘中预演 `run_preview()` 复用同一套计算：T-1 及以前仍走 `db_fresh`，Today 用 realtime overlay，结果只写入 Redis `etf_rotation:preview:{market}`，不写 `ETFMarketRotationSnapshot` / `ETFMomentumSnapshot`。CN 对 Universe+benchmark 一次 Tencent `real()`，US 固定 Yahoo 5 分钟 batch 聚合；失败不 fallback。周期任务为 `etf_rotation_preview_cn`（11:05/14:05/14:35 Asia/Shanghai）与 `etf_rotation_preview_us`（11:05/15:05/15:35 America/New_York），相对 Trend Following Preview 错开 5 分钟。API：`GET /api/v1/etf-rotation/preview`。Redis 写入失败必须让 Celery Preview task 失败。

### Trend Following

`trend_following/service.py` 对固定 CN/US Universe 计算特征、排名和纯趋势状态（IDLE / WATCHING / CANDIDATE / TRENDING / WEAKENING / BROKEN），不维护理论持仓或交易动作。所有股票（包括 CN CSI2000）统一 DB-only；仅 benchmark 可用 `db_fresh` 只读补尾部，远程结果不落库。支持从历史快照向后重建，因此变更规则时要考虑旧日期重算和 invalidate 行为。

盘中预演 `run_preview()` 用当日临时日线复用同一套计算，结果只写入 Redis `trend_following:preview:v2:{market}`，不写正式 snapshot。CN 固定 `easyquotation` 腾讯全市场快照，US 固定 Yahoo 5 分钟 batch 聚合；失败不 fallback 到其他 realtime provider。周期任务为 `trend_following_preview_cn`（11:00/14:00/14:30 Asia/Shanghai）与 `trend_following_preview_us`（11:00/15:00/15:30 America/New_York）。API：`GET /api/v1/trend-following/preview`。

## 报告和通知

- `reporting/` 定义 report 类型、schema、本地化、Markdown/Jinja 渲染和可选图片转换。
- 根 `templates/report_*.j2` 是报告模板；昂贵查询在调用方完成后注入模板。
- `notification/` 先将消息写入 `notification`，再按 route 过滤 Telegram/ntfy 并执行原有去重/冷却；推送状态不入库。
- 通知失败通常应隔离到单渠道，不应抹掉成功分析；保持现有 fail-open/finalize 语义。

## 测试定位

主测试都在根 `tests/`，命名通常直接映射模块：

- API/鉴权：`test_auth_api.py`、`test_*_api*.py`
- 数据库/迁移：`test_*_repository.py`、`test_*_migration.py`
- 行情：`test_market_data_*.py`、`tests/market_stream/`
- Celery：`test_celery_*.py`、`test_task_*.py`
- 策略引擎：`test_quant_*.py`、`test_etf_rotation_*.py`、`test_trend_following_*.py`

运行：

```bash
uv run pytest tests/test_<area>.py -q
uv run ./scripts/ci_gate.sh
```

测试默认离线，只有明确标记 `network` 的用例可访问公网。优先使用 fake repository、fake provider、依赖注入和临时目录；不要通过全局 monkeypatch 把测试连到真实用户数据库。

## 后端改动检查表

1. 入口层是否只处理协议，业务规则是否在所属领域。
2. 用户级数据是否按 `uid` 隔离，管理员权限是否显式。
3. 日线是否仍为前复权，查询是否意外写库。
4. 时间是否 aware UTC，市场日期/时区是否正确。
5. Celery 名称、queue、schedule、TaskRecord 与回调是否一致。
6. Qlib 是否仍隔离于主环境和数据库。
7. 外部服务失败是否有明确 partial/failed/fallback，而非伪造成功数据。
8. schema 变更是否包含 ORM、Alembic 和迁移测试。
9. 聚焦测试与离线门禁是否通过。

## BTC 策略

`crypto/` 负责 BTCUSDT 原生15m/1h指标、LONG/FLAT与ATR风险；`integrations/crypto` 仅做 Binance 公共 REST。
Beat `crypto_btc_strategy` 每15m收盘后一分钟执行，只读闭合K线，不持久化行情，不维护行情WS/Redis/同步进程。
仓储原子写state与15m快照，以唯一时间点和行锁防重放及跳步；已有快照按15m顺序补算，冷启动只算最新。
`0060_crypto_positions` 增加0–1仓位、平均成本及snapshot前后仓位/delta；绩效和执行/持仓周期从完整连续snapshot动态派生，不新增表。
这是共享研究状态，不是用户仓位/Paper Trading。不要添加资金、订单或AI执行。详见 `docs/crypto-btc.md`。

## A 股行业强度

`industry_strength/` 通过 `MarketDataService` 读取扶摇指数及现有股票日线，独立保存
`industry_strength_snapshot`；正式任务同事务整表替换 `industry_strength_constituent` 最新成分。
成分 HTTP 只读该表，Trend Rank 批量读取最新 CN 正式快照并物化（可空），历史补算不覆盖最新成分。
三个扶摇能力仅支持 CN；指数无股票复权语义，使用 `IndexDailyBar`。
正式任务和 Preview 共用计算流程：行业指数历史请求 API，个股历史以 `db_only` 读取完整窗口；不缓存计算输入，
不写 `stock_daily`，不修改 ETF Universe。
正式 Breadth 仅当日收盘计算，不做当前成分历史回填。配置、状态和覆盖规则见 `docs/industry-strength.md`。
