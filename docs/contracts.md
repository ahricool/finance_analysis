# U 本位永续合约行情

页面 /crypto/contracts：共享的 Binance USDT 结算永续合约（PERPETUAL / TRADIFI_PERPETUAL）观察列表，已登录用户可查看，管理员可查询交易所目录、增删标的。
不支持现货、币本位、交割合约、盘口、交易下单、信号或预测。默认仅显示合约列表；点击普通单元格展开最近 24 小时原生 1 分钟 K 线与指标，可切换日 K，点击同一行收起。点击合约代码或锚定标的打开统一证券详情，不改变展开状态。管理员在列表标题旁通过「添加合约」搜索并连续添加，行内「删除」经确认后移除标的及日线。展开区展示报价、资金费率、均线及最新 K 线 OHLC；均线按对应周期已结束且连续的 K 线计算，数据不足留空，不提供股票趋势/形态或预测。

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
