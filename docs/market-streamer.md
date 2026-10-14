# 长桥实时行情 Streamer

`finance-analysis-stream` 是独立于 FastAPI、Celery Worker 和 Celery Beat 的常驻进程。它只从 PostgreSQL
读取美股 WatchList，并把实时 Quote、1 分钟 K 线、订阅状态和心跳写入 Redis；不会向 PostgreSQL 写行情数据。

## 启动

```bash
uv run finance-analysis-stream
docker compose -f docker-compose.dev.yml up -d --build streamer
docker compose -f docker-compose.prod.yml up -d streamer
```

进程启动后先获取 `lock:market_stream:leader`。锁使用唯一 token、有限 TTL 和 token 校验续租/释放；锁丢失时
streamer 主动停止，避免两个实例同时写实时状态。

## 动态订阅

服务默认每 5 秒通过现有 `get_watch_list_codes_by_market("US")` 读取所有用户 WatchList 的并集。新增标的先建立
Quote 和 1 分钟 K 线订阅，再从 Redis 或长桥同步接口预热近期 K 线；预热期间的推送保存在内存 buffer，随后按
`bar_time + trade_session` 合并。删除标的时串行取消两个订阅，清理进程内状态，但 Redis 数据保留 2 小时。

连接健康检查失败后，服务按 1、2、4、8、16、30 秒上限并附加 jitter 重建 Context。每次重建都会增加
connection generation、重新注册回调、重新读取 WatchList 并重新订阅/预热。旧 connection generation 和旧 symbol
generation 的事件或预热结果会被丢弃。

## Redis Keys

| Key | 类型 | 用途 |
| --- | --- | --- |
| `rt:quote:{symbol}` | Hash | 最新合并 Quote |
| `rt:candle:1m:{symbol}:current` | Hash | 当前 1 分钟 K 线 |
| `rt:bars:1m:{symbol}:index` | Sorted Set | 分钟时间戳索引 |
| `rt:bars:1m:{symbol}:data` | Hash | 时间戳到 K 线 JSON 的稳定映射 |
| `rt:subscription:{symbol}` | Hash | symbol 订阅和 warmup 状态 |
| `rt:streamer:heartbeat` | Hash | streamer 状态，TTL 30 秒 |
| `lock:market_stream:leader` | String | 单实例 Leader Lock |

历史 K 线使用稳定的分钟时间戳作为 Sorted Set member 和 Hash field，因此同一分钟更新不会残留多个 JSON member。

## 配置

`REALTIME_REDIS_URL` 留空时回退 `REDIS_URL`。其余可选配置：

- `MARKET_STREAM_WATCHLIST_POLL_SECONDS=5`
- `MARKET_STREAM_HEARTBEAT_SECONDS=5`
- `MARKET_STREAM_LEADER_LOCK_TTL_SECONDS=30`
- `MARKET_STREAM_REDIS_FLUSH_INTERVAL_MS=250`
- `MARKET_STREAM_WARMUP_CONCURRENCY=3`
- `MARKET_STREAM_BAR_LIMIT=420`

长桥凭证及 URL、region、日志和语言配置继续使用项目已有的 `LONGBRIDGE_*` 配置。

## 页面行情传输

`/api/v1/market-data/ws` 和 `/api/v1/market-data/events`（HTTP SSE）使用同一个快照构建器。
默认 `scope=watch-list` 读取当前用户自选列表，报价通过 MarketDataService 按市场优先级获取，
一分钟趋势/形态仍只读Streamer Redis。`scope=holdings&market=CN|US` 返回当前用户该市场
的账户/持仓估值快照，不要求持仓已在自选中。WS使用会话Cookie，SSE使用现有HTTP会话鉴权；
均不接受客户端uid，约每5秒推送一次，不写行情数据库或Streamer状态。

浏览器WS连续两次连接/快照超时失败后固定回落SSE，后续不再自动尝试WS；
SSE 建连后立即发送注释帧，查询行情期间每10秒发送心跳；慢查询不会启动额外的快照请求。
浏览器等待 HTTP 建连最多60秒，建连后按响应字节（含心跳）检测30秒无活动，
不以行情更新间隔判断连接失效。行情时间戳仍只在收到完整快照时更新。
SSE 失败按5/10/20/30秒退避，仅重连SSE，收到有效行情后重置退避；未授权停止重试。
切换市场或离开页面取消旧连接和未完成的快照协程。
