# U 本位永续合约行情

页面 /crypto/contracts：共享的 Binance USDT 结算永续合约（PERPETUAL / TRADIFI_PERPETUAL）观察列表，已登录用户可查看，管理员可查询交易所目录、增删标的。
不支持现货、币本位、交割合约、交易下单、信号或预测。默认仅显示合约列表；点击普通单元格展开最近 24 小时原生 1 分钟 K 线与指标，可切换日 K，点击同一行收起。点击合约代码或锚定标的打开统一证券详情，不改变展开状态。管理员在列表标题旁通过「添加合约」搜索并连续添加，行内「删除」经确认后移除标的及日线。展开区展示报价、资金费率、均线及最新 K 线 OHLC；均线按对应周期已结束且连续的 K 线计算，数据不足留空，不提供股票趋势/形态或预测。

## 持久化与采集

- 迁移 0096_contract_market 删除旧 BTC 策略 state/snapshot 表及专属任务记录。原策略任务、页面、首页概览和 BTC 现货预测后台采集退役。迁移不可逆，回滚需迁移前备份。
- futures_contract 存共享标的、分类及 `underlying_symbol`；默认 19 个由迁移插入（排除币本位 BTCUSD_PERP），空库 bootstrap 同样只执行一次 seed。后续删除不会在重启时恢复。
- 迁移 `0101_contract_underlying` 按已有合约代码、分类回填锚定标的，保留原列表及全部日线。空库 bootstrap 同样回填。新合约以交易所 `baseAsset` / `underlyingType` 为准（缺 baseAsset 时使用去除 USDT 后缀的合约代码），不信任客户端填写的锚定标的。
- `NVDAUSDT → NVDA.US`、`SOXLUSDT → SOXL.US` 等美股/ETF 复用完整现货证券详情；`BTCUSDT → BTC.CRYPTO` 等加密货币暂只展示行情与历史 K 线空态。商品、韩股、无法确认可用现货证券代码的交易所别名以 `.OTHER` 标识并同样展示空态，不调用股票行情或研究接口，也不把永续合约价格当成现货价格。既有分类推断不能确认时使用空态；后续可在数据库修正锚定代码。
- futures_daily_bar 存 UTC 已闭合日线（原生未复权），主键为合约与开盘毫秒时间戳。首次向前读取约五年，后续补齐到最近日；移除合约同时级联删除日线。
- 既有 Streamer leader 使用 Binance USD-M 公共 WS `wss://fstream.binance.com/market/stream` 订阅共享列表的 ticker、markPrice@1s、kline_1m、kline_1d（仅当日预览）。每秒合并推送写 Redis；不再周期 REST 拉取报价或写入 DB 日线。动态增删标的重建订阅；异常/24 小时连接关闭时退避重连。
- Redis 保持原键：报价 60 秒 TTL；近 1440 个自然分钟的窗口（24 小时 TTL，读取时裁剪）；当日预览 180 秒 TTL。资金费率不能延长过期报价。首次订阅、重连检查完整连续分钟网格；不足时 REST 从最早缺口补齐，运行中每分钟检查缺口，完整时不调用 REST。WS 的闭合标志优先，未收到闭合确认的历史分钟不能用于策略；缺失不补零。窗口含当前形成中的一分钟。
- 日线每日 UTC 00:30（北京时间/新加坡时间 08:30）由 Celery Beat `contract_daily_sync` 投递 ingestion 队列，支持任务中心手动运行。日线在 UTC 00:00 闭合；同步仅取已闭合至少 30 分钟的日 K。按交易所 onboardDate 与最近 1825 个自然日确定历史范围；历史完整则仅补目标日，缺失任意历史日期则分页全量重新同步，源数据缺损不覆盖原记录。每标的独立核对，失败可重试，已成功标的保持幂等；独立任务锁防并发。新标的会在下一次定时/手动日线任务初始化。
- 公共 REST 保留 /fapi/v1/exchangeInfo、/fapi/v1/time、/fapi/v1/klines，用于目录、时间校准及历史补齐。可设置 BINANCE_FUTURES_REST_BASE_URL，默认 https://fapi.binance.com；无 API key。默认标的未上市、停牌或交易所不可用时保留列表，显示暂无行情。
- 24h 成交额原始口径为 USDT，涨跌幅为百分数；资金费率为原始比例，前端乘以 100 显示为百分数。

## API

| 方法 | 路径（/api/v1/crypto） | 用途 |
| --- | --- | --- |
| GET | /contracts | DB 标的与 Redis 行情快照 |
| GET | /contracts/search?q= | 交易所正在交易的 USDT 本位永续搜索 |
| POST | /contracts | 管理员添加标的 |
| DELETE | /contracts/{symbol} | 管理员移除标的 |
| GET | /contracts/{symbol}/bars?interval=1d 或 1m | 只读 DB 日线或 Redis 分钟线 |
| WS | /contracts/ws?symbol= | 共享行情与选中合约 K 线快照 |
| GET SSE | /contracts/events?symbol= | 同结构回退数据流 |

GET 快照、搜索、添加响应及 WS/SSE 的合约项均包含 `underlying_symbol`（无法解析时为 null）。

本站后端 WS 每 5 秒推送最新快照（上游 Binance WS 缓存每秒合并更新）；interval 参数选择 1d 或 1m，避免重复传送非当前周期的 K 线；连续两次失败后使用 SSE，断开自动重连。前端不连接 Binance。

官方 WS 路由与迁移规范：[Binance USD-M WebSocket Market Streams](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Connect)。

合约列表按 UTC 00:00 划分交易日，仅使用已闭合分钟线，复用日内期权的 5/15/30/60 分钟趋势评分与已确认形态识别。报价、分钟线延迟或连接断开时，页面隐藏当前机会。Streamer 在闭合分钟变更及历史补齐时计算分析摘要。
页面的 WS/SSE 订阅携带 `delta=true`。每次连接先接收完整基线，随后按连续 revision 合并字段变化；滚动分钟按 timestamp 匹配，仅传删除、新增和修订。无变化发送空操作，断线后重新建立基线。

## 五分钟结构与流动性

列表的比较时点 T 为最近已结束的 UTC 五分钟边界。1h 指标使用跨日滚动窗口 [T−60m, T)。各资金类指标来自 USD-M 原生 5m 数据。接口、权限及时间定义见 [Binance Market Data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)。

| 字段 | 来源与单位 | 与 T 的关系 |
| --- | --- | --- |
| `metrics.accounts` | globalLongShortAccountRatio，全市场净多 / 净空账户数（倍），同时保留多空账户占比 | T 期末采样 |
| `metrics.top_accounts` | topLongShortAccountRatio，保证金余额前 20% 用户的账户数比、账户占比 | T 期末采样 |
| `metrics.top_positions` | topLongShortPositionRatio，同一群体的净多 / 净空仓位规模（倍），longAccount / shortAccount 存为持仓占比 | T 期末采样 |
| `metrics.oi`、`oi_change` | openInterestHist 的 quantity 为合约标的数量，usdt 为名义价值；1h 变化率为 quantity(T) / quantity(T−60m) − 1 | 两个精确端点 |
| `metrics.taker`、`buy_share` | takerlongshortRatio，buy / sell 为同单位主动成交量，ratio 为原接口买卖倍数；1h 占比为十二桶买量之和 / 十二桶买卖总量 | 原生 timestamp 是桶起点，归一边界加 5m |
| `metrics.price_change`、历史 `price` | 已闭合成交价 1m K 组成的 5m 开收边界，保留来源。1h 使用末收 / 首开 − 1 | 完整 60 根，缺一分钟即为空 |
| `mark` | 市场流 markPriceUpdate 的 p / i / r / T / E，分别为标记价、指数价、资金费率、下次结算、事件时间。basis 为 p / i − 1 | 与 ticker 分开缓存，各 60 秒 |
| `book` | 每 5 秒批量读取 bookTicker 的 bidPrice / askPrice，spread_bps 为价差除以买卖中点再乘 10000 | time 为撮合时间，60 秒有效 |
| `/depth` | 展开期间向 FA 续租，同一标的的所有用户共用 Streamer 的 limit=10 深度快照。bids / asks 各自累加价格 × 数量（USDT），分别附实际档数 | T 为交易所快照时间，15 秒有效 |

历史每条记录的 `timestamp` 是归一后的 UTC 毫秒边界，各组的 `source_time` 是币安原始时间。账户占比、资金费率、偏离率、1h 变化及主动买入占比均为小数比率，前端乘 100 显示百分数；原有 `quote.change_pct` 已是百分数。历史副图的主动买入占比使用各自 5 分钟桶。零分母、缺桶、缺基准、形成中 K、缺权限按字段显示空值。列表 `metrics.status` 分组记录本次采集结果（ok / partial / missing / unauthorized / rate_limited / unavailable）。BTC 等常规标的与有交易时段的 TradFi 合约使用相同窗口。

### 后台同步与迁移

1. 在业务库执行 `uv run alembic upgrade head`。迁移 `0103_futures_metric_sample` 新增以 (symbol, period, timestamp) 为主键的表。移除观察标的停止采集，已入库统计历史继续可查。
2. 在 Streamer 的服务端环境配置可选 `BINANCE_FUTURES_MARKET_DATA_KEY` 后重启相应服务。大户两项按官方 MARKET_DATA 权限发送 X-MBX-APIKEY，仅限 HTTPS 的 fapi.binance.com；缺少专用 Key 时其余指标继续采集。
3. 按常规流程更新 Server、Streamer 和 Web。单个当选 Streamer 优先同步最新一小时，各来源按缺口写入。随后向过去分页查找最近 30 天内的可用样本，按来源保存 Redis 游标；游标丢失从近端重查，数据库 upsert 保留其他成功来源。历史 K 按需补相应原生分钟。每页最多 240 个五分钟边界，统计 API 每秒最多两次（官方 IP 限制 1000 次 / 5 分钟）；遇 429 / 418 按 Retry-After 暂停。最新截面缺数在本窗口内重试，历史完成后每日重新查缺。

### Agent 历史查询

使用已登录 FA 会话。start / end 均为包含端点的 UTC 毫秒值，最多 31 天；limit 为 1–500，结果按时间升序。

```http
GET /api/v1/crypto/contracts/BTCUSDT/metrics?start=1795672800000&end=1795676400000&limit=12
```

若 `next_start` 非空，下一页将 start 设为该值并沿用 end。空页返回 `items: []` 与 `next_start: null`。每行包含 symbol、period、timestamp、price、oi、taker 及三组多空结构，缺失组为 null。列表 GET 和 WS/SSE 仅携带该边界的最新摘要，历史副图在展开后选择指标时读取最近 24 小时。

### 验证记录（2026-11-26）

- 离线 pytest 使用固定跨 UTC 午夜窗口，100→103、1000→1080、主动买卖总量 650/350、账户占比 60%/40% 分别得到 +3%、+8%、65%、1.50 倍。另覆盖缺桶、零成交、仅名义价值上涨、旧缓存、权限缺失、限流、乱序行情、游标重试和历史分页。
- Vue/Vitest 与 Playwright Chromium 使用模拟 FA 接口，覆盖面板、订阅回退、增量清空、普通用户和管理员的展开、标的跳转、懒加载历史及行情格式。
- 独立临时 PostgreSQL 16、Redis 7 和真实 Binance 公共 REST 联调，BTCUSDT 在 2026-11-26 07:00 UTC 截面的 13 条边界记录成功落库，读取得到 1h 价格 −0.43196%、OI 数量 −0.10048%、主动买入占比 43.22033%、账户多空比 2.5423。同次核验了 BBO 及双边各 10 档深度名义额。真实市场 WS 的 markPriceUpdate 经 ContractCollector.flush 写入 Redis，包含标记价、指数价、资金费率和下次结算时间。
- 大户两项的带 Key 成功路径通过模拟 HTTP 检查请求头与目标主机；真实采集联调使用无专用 Key 配置，验证局部降级。30 天全观察池回填的恢复行为以分页用例验证。

| 本地验证 | 结果 |
| --- | --- |
| `uv run pytest tests/contracts -q` | 40 项通过 |
| `uv run ./scripts/ci_gate.sh` | 语法、flake8、确定性检查与后端离线门禁通过 |
| Web `pnpm test` | 164 个文件，1115 项通过 |
| Web `pnpm exec playwright test contracts.spec.ts` | Chromium 两个页面用例通过 |
| Web `pnpm run build`、`pnpm run lint` | 构建通过；lint 无错误，测试组件定义有两个既有警告 |
| PostgreSQL 16 | 验证空库建表和已有 0102 版本标记升级到 0103 |
