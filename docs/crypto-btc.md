# BTC 行情与策略

仅支持 Binance Spot BTCUSDT。LONG/FLAT 是共享研究状态，不执行真实交易，不接股票 Provider 链。

## 两条独立链路

- 页面行情：Browser → Binance 公共 REST / WebSocket。
- 策略：Celery Beat → Binance REST 15m / 1h → evaluate → PostgreSQL 状态与快照 → REST → Browser。

`useBinanceBtcMarket()` 使用 `https://data-api.binance.vision/api/v3/klines`，每次加载最近 500 根；周期为
`1m / 5m / 15m / 1h / 4h / 1d / 1w / 1M`（没有 1Y）。页面只维护一个
`wss://data-stream.binance.vision/ws` 连接，订阅 `btcusdt@aggTrade` 更新价格，以及当前周期的
`btcusdt@kline_<interval>` 更新最后一根 K 线。周期切换先读取 REST，再退订旧周期、订阅新周期。
旧 REST 请求会取消，迟到结果与不匹配周期的事件被忽略；请求期间的实时更新优先于 REST。

REST 失败显示错误并允许手动重试。WS 断开后 3 秒重连，重连成功读取一次当前周期窗口补齐图表；无 HTTP 轮询兜底。
浏览器需能访问 Binance 公共域名；后端不代理连接。卸载时取消请求、关闭连接并清理定时器。

`useCryptoStrategy()` 独立轮询后端策略（60 秒），错误、加载和重试与行情完全分开。首页 BTC 概览显示策略评估价格，非实时行情。

## 后端策略

`scheduled.crypto_btc_strategy` 使用 `analysis` 队列，在 UTC 每小时 `01/16/31/46` 分执行（每个 15m 收盘后一分钟），
沿用现有任务生命周期、状态记录和队列路由。HTTP 超时 10 秒，最多 3 次请求尝试；任务失败可再重试 2 次、间隔 30 秒。

任务以 Binance `/api/v3/time` 返回时间确定最近 15m 收盘边界，分别请求：

- `15m` 最近 100 根：EMA20、ATR14、前 20 根突破与成交量比。
- `1h` 最近 200 根：EMA20、EMA50、Market Regime。

窗口包含指标预热（不是只取 EMA50 的 50 根种子）。与旧 7 天分钟聚合窗口相比，EMA/ATR 种子窗口变化可能造成细微数值差异。
`endTime` 设置为边界减 1ms；Binance 包含式 close time 加 1ms 转成内部排他收盘边界，并再次剔除未闭合线。
最近目标 K 线或连续最低指标窗口不足时任务失败，不推进策略状态或快照。无历史行情回填、持久化或本地聚合。
停机后下一次只评估最新收盘时间，不补造停机期间信号；原 LONG/FLAT 与止损状态保留。

规则保持：

1. 1h EMA20 > EMA50 且 Close > EMA50 为 BULL，反向为 BEAR，其余 RANGE。
2. 15m Close 严格突破此前 20 根最高 High 且 Volume 大于此前 20 根 Volume 中位数为 BREAKOUT。
3. FLAT 在 BULL + BREAKOUT 时 BUY → LONG，其余 WAIT。
4. BUY 用 15m 收盘价作为 entry，初始止损 `entry - 2*ATR`。入场前该根高点不计入入场后最高价。
5. LONG 更新最高价，跟踪止损 `max(既有止损, 最高价 - 2.5*ATR)`，止损不下移，下限为 0。
6. 15m Close < EMA20 或 Close <= 有效止损时 EXIT → FLAT，否则 HOLD。

EMA 以 SMA 为种子，alpha=2/(period+1)；ATR 使用 Wilder 平滑。状态行锁与唯一评估时间防重放，状态与快照同事务提交。

## 存储、API 与配置

仅保留 `crypto_strategy_state`、`crypto_strategy_snapshot`。`0059_drop_crypto_kline` 删除 `crypto_kline`，不改策略数据；
降级只恢复空行情表，不恢复已删除历史。空数据库仍由既有 metadata bootstrap 创建并 stamp 最新 head。

会话保护的只读接口：

| API | 内容 |
| --- | --- |
| GET /api/v1/crypto/btc/overview | 最新策略快照、当前策略状态 |
| GET /api/v1/crypto/btc/signals?limit=50 | 近期策略快照，limit 1–200 |

已删除 `/btc/klines`、`/btc/status`、`/ws`（此前 `/api/v1/crypto` 前缀），以及行情 Redis、writer leader lock、
`crypto_stream/`、`crypto/realtime.py`、`finance-analysis-crypto-stream` CLI 与 Compose 采集服务。

后端仅保留 `CRYPTO_ENABLED=true`（控制策略任务，页面行情不受影响）和
`BINANCE_REST_BASE_URL=https://data-api.binance.vision`。公开行情不需要密钥。

部署：`bash deploy.sh` 会更新服务、执行既有启动迁移，并通过 `--remove-orphans` 清理移除的采集容器。
原生运行的旧采集进程也应停止；无需启动新常驻行情进程。

## 验证

```bash
uv run pytest tests/crypto tests/test_celery_schedule.py tests/test_celery_task_structure.py -q
cd web
pnpm exec vue-tsc -b
pnpm run test
pnpm exec playwright test e2e/crypto-btc.spec.ts
```

测试通过 HTTP / WebSocket mock 离线验证。可选 PostgreSQL 并发事务测试使用专门临时测试库的
`CRYPTO_TEST_POSTGRES_URL`，自行创建清理独立 schema，不连接应用数据库。
协议参考 [Binance WebSocket](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams)
和 [REST Market Data](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints)。
