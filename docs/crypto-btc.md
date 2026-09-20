# BTC 行情与策略

仅支持 Binance Spot BTCUSDT。每个 strategy_key + symbol 拥有独立研究状态，LONG/FLAT 是兼容标签，不执行真实交易，不接股票 Provider 链。

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
对每个 strategy_key + symbol 独立检查：冷启动没有历史快照时只计算最新闭合15m，不制造历史信号。已有快照时，从最后 `evaluated_at + 15m` 到当前收盘依次补算。
所有启用策略共用一次 server time 和行情读取：先统一获取含所有策略最早缺失周期预热窗口的原生15m/1h数据，再按 `close_time <= evaluation_at` 切片，每次取最多100/200根；
因此每一步指标与当时正常运行采用相同窗口，不使用未来K线。通常每个interval只请求一次；超过Binance单次1000根上限时按页取完需要的窗口，
不逐个evaluation请求，也不保存这些行情。
每个evaluation独立通过 `evaluate_once()` 原子提交。中途失败后保留已成功的快照，下次从断点继续；
数据库只锁对应 strategy_key + symbol 的状态行；锁内再次检查最新快照，拒绝跨过15m缺口，同时间点只会写入一次。

规则保持：

1. 1h EMA20 > EMA50 且 Close > EMA50 为 BULL，反向为 BEAR，其余 RANGE。
2. 15m Close 严格突破此前 20 根最高 High 且 Volume 大于此前 20 根 Volume 中位数为 BREAKOUT。
3. FLAT 在 BULL + BREAKOUT 时 BUY → LONG，其余 WAIT。
4. BUY 用 15m 收盘价作为 entry，初始止损 `entry - 2*ATR`。入场前该根高点不计入入场后最高价。
5. LONG 更新最高价，跟踪止损 `max(既有止损, 最高价 - 2.5*ATR)`，止损不下移，下限为 0。
6. 15m Close < EMA20 或 Close <= 有效止损时 EXIT → FLAT，否则 HOLD。

EMA 以 SMA 为种子，alpha=2/(period+1)；ATR 使用 Wilder 平滑。状态行锁与唯一评估时间防重放，状态与快照同事务提交。

## 静态策略注册表

`crypto/registry.py` 的 `StrategyDefinition(key, display_name, evaluate, enabled)` 是唯一代码注册表。
当前只启用 `btc_breakout_v1` / Breakout V1，key不随显示名变化。新增策略注册一个定义即可，不需要复制scheduler。
服务对每个启用策略分别确定cold start/catch-up范围，用同一份闭合行情按时间顺序计算。
一个策略失败不阻止其它策略完成；所有可执行策略处理后任务报错以触发既有重试，已提交周期不会重算。
禁用策略不计算，但保留历史详情可读；没有动态配置表或UI启停操作。

## 存储、API 与配置

仅保留 `crypto_strategy_state`、`crypto_strategy_snapshot`。状态与snapshot的新增仓位字段见下节。`0059_drop_crypto_kline` 删除 `crypto_kline`，不改策略数据；
降级只恢复空行情表，不恢复已删除历史。空数据库仍由既有 metadata bootstrap 创建并 stamp 最新 head。

会话保护的只读接口：

| API | 内容 |
| --- | --- |
| GET /api/v1/crypto/btc/strategies | 注册策略列表、启用状态、当前仓位、最近动作/时间 |
| GET /api/v1/crypto/btc/strategies/performance | 所有启用策略的绩效摘要，不含历史明细 |
| GET /api/v1/crypto/btc/strategies/{strategy_key}/overview | 指定策略最新快照与状态 |
| GET /api/v1/crypto/btc/strategies/{strategy_key}/signals?limit=50 | 指定策略近期快照，limit 1–2000 |
| GET /api/v1/crypto/btc/strategies/{strategy_key}/signals?start=…&end=…&actions_only=true&limit=2000 | 当前图表范围内最近最多2000条BUY/EXIT，UTC aware边界 |
| GET /api/v1/crypto/btc/strategies/{strategy_key}/performance | 指定策略派生绩效、近期执行/完整周期、净值曲线 |

未知key返回404。原 `/btc/overview`、`/btc/signals`、`/btc/performance` 共享同一个handler，作为Breakout V1兼容alias。
首页继续使用overview alias；BTC页全部使用显式strategy_key路径。仓储所有状态/快照读取和写入都必须显式传key与symbol。

已删除 `/btc/klines`、`/btc/status`、`/ws`（此前 `/api/v1/crypto` 前缀），以及行情 Redis、writer leader lock、
`crypto_stream/`、`crypto/realtime.py`、`finance-analysis-crypto-stream` CLI 与 Compose 采集服务。

后端仅保留 `CRYPTO_ENABLED=true`（控制策略任务，页面行情不受影响）和
`BINANCE_REST_BASE_URL=https://data-api.binance.vision`。公开行情不需要密钥。

部署：`bash deploy.sh` 会更新服务、执行既有启动迁移，并通过 `--remove-orphans` 清理移除的采集容器。
原生运行的旧采集进程也应停止；无需启动新常驻行情进程。

## 仓位与迁移

`0060_crypto_positions` 在0059之后，只修改现有两张策略表，不新增execution或trade表：

| 表 | 新字段 | 语义 |
| --- | --- | --- |
| state | position_pct | Decimal，0–1；真正的当前仓位 |
| state | average_entry_price | 当前平均成本；空仓为null |
| snapshot | position_before / position_after / position_delta | 评估前后仓位与差值，非零delta就是一次虚拟执行 |
| snapshot | average_entry_price | 操作后的平均成本；EXIT为null |

保留 `position_state` 与 `entry_price` 兼容字段，随仓位/平均成本同步；`position_pct > 0` 为LONG，0为FLAT。
首次入场时间、入场后最高价、止损仍在state中。当前规则的BUY固定0→1、HOLD保持仓位、EXIT→0、WAIT为0；
没有新增加仓、减仓条件。`change_position()` 的纯函数为未来部分仓位提供成本计算：

- 加仓：`(old_pct * old_avg + (new_pct-old_pct) * price) / new_pct`。
- 减仓：平均成本不变；首次entry_time保留。
- 清仓：平均成本、entry_time、最高价、止损清空。

迁移已有LONG state为1、成本取entry_price，FLAT为0/null。旧snapshot只根据原position_state填position_after，
其before/delta/成本保持null，不根据BUY/EXIT猜测历史。新snapshot由仓储要求完整填写仓位变化，state更新与snapshot插入同事务。
数据库约束限制0–1与delta差值。回滚0060删除新增列与约束，保留原状态/快照及兼容字段；部署时Beat/Worker/API需一起升级，避免旧Worker继续写旧格式。

`0061_crypto_strategy_keys` 接续0060：两表增加strategy_key，已有行统一归属 `btc_breakout_v1`。
state主键改为 `(strategy_key, symbol)`；snapshot唯一约束改为 `(strategy_key, symbol, evaluated_at)`。
0061降级仅在不存在其它策略数据时允许，避免多个策略折叠造成覆盖或误删；保留已有Breakout数据。
空库metadata与迁移后的两张策略表结构一致，没有第三张业务表。

## 绩效口径

绩效为快照的动态派生视图，不持久化equity/return/drawdown，无缓存，也不访问实时Binance价格。
从最新连续且仓位字段完整的一段快照计算，遇到缺失15m、仓位不连续或旧不完整字段就重新确定有效起点。
每个策略独立从1开始；API明确返回 `performance_start_at`、`performance_end_at` 和 `running_days`；无法确认入场的旧open cycle不计完整交易。

- 初始equity=1；`equity *= 1 + previous.position_after * (price / previous.price - 1)`。
- total_return = 最后equity−1，包含未退出持仓截至最新15m的浮动损益。
- running_days = (performance_end_at − performance_start_at) / 86400秒。
- annualized_return = `equity ** (365 / running_days) - 1`，仅days>0时计算CAGR；短周期也不截断数学值，页面同时展示运行天数。
- drawdown = `equity / running_peak - 1`；max_drawdown取所有15m快照最小值，以负数比例返回，包含持有期回撤。
- 完整cycle从0→正仓位开始，首次正仓位→0结束；中间可有部分仓位变动。
- cycle realized_return = 退出时equity / 入场时equity−1，体现中间仓位比例；平均成本为清仓前平均成本，另返退出价格及持有秒数。
- win/loss分别为完整cycle收益>0/<0；0收益为平手。win_rate = wins / closed_trades（分母含平手）；未完成/未知入场cycle不参与。
- average_trade_return为完整cycle收益算术平均；best_trade/worst_trade为其最大/最小收益比例；没有完整cycle时这四个指标为null。
- execution_count计算有效区间内非零delta快照；recent_executions/recent_trades倒序最多50条；统计始终使用有效区间全部15m净值点。equity_curve最多返回1000个均匀抽样点（含首尾）；equity_points_total说明原始点数，抽样不改变任何收益/回撤统计。

Performance API还返回 `current_position: {position_pct, average_entry_price}`、closed_trades、wins、losses、breakeven等，Decimal序列化为字符串。
前端根据独立的Binance实时price计算 `price/average_entry_price - 1`，以及 `position_pct * price_return` 浮动贡献；
它们是当前成本视角的显示值，不替代15m净值曲线。

## K线标记

页面按Market、Strategy、Performance展示；简单Strategy selector同时切换指标、绩效、信号、标记，Binance连接和K线不重载。两个以上启用策略才展示横向绩效表。K线仅显示 `↑ BUY` / `↓ EXIT`，不会为WAIT/HOLD打标。
标记使用已有策略snapshot的evaluated_at和price，仅显示所选策略，点击展示策略名称、原始时间、操作、价格、前后仓位、regime/setup/reason。
1m/5m/15m按精确evaluated_at定位；1h/4h/1d/1w/1M映射至已经加载的Binance candle `[openTime, closeTime)`，
月线/周线直接采用返回的真实边界，不假定固定月长。范围外标记不显示。同一大周期内多个信号保留并错开文字。
标记仅请求后端信号范围，不触发行情请求；行情、策略/绩效的错误互不影响。

当前明确不实现账户、资金、BTC数量、订单/fill、费用/滑点、杠杆、真实交易、仓位优化规则、Sharpe/波动率、跨策略资金分配、回测框架或独立execution/trade表。

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
