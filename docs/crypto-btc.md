# BTC 交易模块 V0.1

独立的 Binance BTCUSDT Spot 行情与确定性策略模块。LONG/FLAT 表示策略信号状态，不代表真实资产、订单或 Paper Trading；不接股票 MarketDataService Provider 链。

## 运行

```bash
uv sync
uv run alembic upgrade head
uv run finance-analysis-crypto-stream
```

使用与主服务相同的 `DATABASE_URL`、`REDIS_URL`。公开行情无需 API Key。`.env.example` 中：

| 配置 | 默认值 |
| --- | --- |
| CRYPTO_ENABLED | true |
| CRYPTO_SYMBOL | BTCUSDT（其它值拒绝启动） |
| BINANCE_REST_BASE_URL | https://api.binance.com |
| BINANCE_WS_BASE_URL | wss://stream.binance.com:9443 |
| CRYPTO_HTTP_FALLBACK_INTERVAL_SECONDS | 60 |
| CRYPTO_WS_RECONNECT_INTERVAL_SECONDS | 60 |
| CRYPTO_WS_TIMEOUT_SECONDS | 20 |
| CRYPTO_INITIAL_HISTORY_DAYS | 30（允许 4–90 天） |

dev/prod Compose 均有独立 `crypto-streamer` 服务，`restart: unless-stopped`，依赖 PostgreSQL/Redis，沿用主应用镜像；不在 FastAPI、Beat 或 Celery Worker 内运行。`CRYPTO_ENABLED=false` 时进程等待终止，不采集行情。

## 存储与计算

- `crypto_kline`：仅保存已收盘 BTCUSDT 1m；`UNIQUE(symbol, interval, open_time)` upsert。价格和数量为 `Numeric(30,12)`；JSON 传输为十进制字符串。
- `crypto_strategy_state`：当前 FLAT/LONG、入场价/时间、入场后最高价与止损。
- `crypto_strategy_snapshot`：每个完整 15m 评估时间的不可变结果；`UNIQUE(symbol, evaluated_at)`。
- `0044_crypto_btc` 从 `0043_investment_timeline` 升级，包含三张表及约束。
- Redis `crypto:BTCUSDT:realtime:v1`（180s TTL）仅为即时视图：当前 K 线、最近5根已收盘线、采集模式、连接/更新时间、最后错误和最新策略。Redis 失败不阻止 PostgreSQL 保存历史与策略。

所有时间为 aware UTC。内部 `close_time` 是**排他的下一分钟整点**（Binance 的包含式 close time 加 1ms）。聚合区间为 `[00:00,00:15)`、`[00:00,01:00)` 等 UTC 边界；缺少任何一分钟或包含未收盘分钟时，不产生完整聚合线。指标使用最近7天内、截至评估时间的连续完整聚合尾部，缺口不被当作相邻样本。

EMA 使用周期内 SMA 作为种子，之后 `alpha=2/(period+1)`。ATR14 使用前收盘计算 True Range，14个 TR 平均值作为种子，之后 Wilder 平滑。

策略：

1. 最近完整1h的 EMA20 > EMA50 且 Close > EMA50 为 BULL；反向为 BEAR；其余 RANGE。不足50根连续1h为 UNKNOWN。
2. 15m Close 严格大于**此前20根** High 最大值，且 Volume 严格大于此前20根 Volume 中位数，为 BREAKOUT；零中位数时 volume ratio 为空。
3. FLAT 仅在 BULL + BREAKOUT 时 BUY → LONG，其余 WAIT。
4. BUY 以该15m收盘价记录入场；初始止损 `entry - 2*ATR`。入场前该根K线的高点不计入入场后最高价。
5. LONG 更新最高价；跟踪止损为 `max(既有跟踪止损, 最高价 - 2.5*ATR)`；有效止损为初始与跟踪止损较大值，初始/跟踪下限为0。
6. 完整15m Close < EMA20_15m 或 Close <= 有效止损时 EXIT → FLAT，否则 HOLD。即使因数据缺口指标预热不足，已有止损仍有效。
7. 冷启动同步历史后仅从最新完整15m建立第一条策略快照，初态FLAT，不伪造此前30天交易。已有快照时从上次评估之后按15m顺序补算。旧快照不因历史K线幂等覆盖而重算。

策略状态行锁及时间去重保证状态与快照同一事务提交；重复/迟到K线不会重复 BUY/EXIT。PostgreSQL session advisory lock 保证只运行一个 BTC 采集主实例。

## 连接与容灾

启动先按 open_time 升序、每页最多1000根REST补齐。空库默认30天；已有数据从最后提交的分钟重新取一根并向前推进。HTTP请求有超时和最多3次重试，进程循环会继续重试；未完成历史补齐前不会用最近5根推进历史游标而跳过中间缺口。

主采集为 `/ws/btcusdt@kline_1m`。连接、接收超时、无效或过期K线等失败进入 `http_fallback`，每60秒读取最近5根REST行情。期间每60秒尝试一次WS；只有收到有效新鲜K线并完成REST对账才恢复 `websocket`，停止HTTP轮询。长期同时断网后复用分页补齐路径追平缺口。只有一个采集循环写入，没有并行WS/REST摄取任务。

SIGINT/SIGTERM 会中断连接、接收或重试等待，结束正在执行的有界数据库事务后关闭WS/HTTP/Redis，释放主实例锁。Redis和网络故障仅改变可用性，不将其伪装成正常实时行情。

前端不连接 Binance。首次读后端最近1000根已收盘K线，再订阅后端WS，更新当前分钟与最近闭合线；历史数组只在闭合线变化时更新，实时价更新只替换图表的单根当前分钟 series。后端WS失败/15秒无有效消息时，每60秒轮询后端REST；每15秒尝试重连，有效消息恢复后停轮询并对账历史。401/4401/4403停止连接重试。卸载页面清理连接和定时器。

## API 与页面

所有HTTP接口由现有会话中间件保护；WS显式检查Cookie及用户，定期复核会话。行情和策略为全站共享研究事实，不按用户分仓。

| API | 内容 |
| --- | --- |
| GET /api/v1/crypto/btc/overview | 最新数据库策略、状态和即时行情 |
| GET /api/v1/crypto/btc/klines?interval=1m&limit=1000 | 最近已收盘1m，升序；limit 1–1000 |
| GET /api/v1/crypto/btc/signals?limit=50 | 历史15m快照，降序；limit 1–200 |
| GET /api/v1/crypto/btc/status | 采集模式和即时状态 |
| WS /api/v1/crypto/ws | 每2秒 `{type:"state", market: ...}`，相同结构覆盖WS和HTTP来源 |

页面 `/research/crypto/btc` 在“研究 → BTC 交易”。显示价、Regime/Setup/Action、EMA、突破/成交量、ATR/止损、LONG/FLAT、1m K线和近期快照。HTTP兜底只显示弱提示。

V0.1未增加手动backfill API；重启crypto-streamer会自动补齐。没有AI、下单、持仓数量、资金、PnL、多币种或多交易所。

## 验证

```bash
uv run pytest tests/crypto -q
# 可选：仅使用专门的临时测试库，测试自行创建和清理独立schema
CRYPTO_TEST_POSTGRES_URL=postgresql+psycopg2://... uv run pytest tests/crypto/test_postgres.py -q
cd web
pnpm exec vitest run src/composables/__tests__/useCryptoBtc.test.ts src/api/__tests__/crypto.test.ts
pnpm run build
pnpm exec playwright test e2e/crypto-btc.spec.ts
```

单元测试通过 fake/HTTP mock 验证Binance协议和切换，不访问真实Binance。浏览器测试使用后端API/WS mock。协议参考 [Binance Spot WebSocket](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams) 与 [REST Market Data](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints)。
