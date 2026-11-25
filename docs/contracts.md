# U 本位永续合约行情

页面 /crypto/contracts：共享的 Binance USDT 结算永续合约（PERPETUAL / TRADIFI_PERPETUAL）观察列表，已登录用户可查看，管理员可查询交易所目录、增删标的。
不支持现货、币本位、交割合约、盘口、交易下单、信号或预测。点击合约代码或锚定标的打开统一证券详情；独立「K 线」按钮仍可切换上方合约日 K 和最近 24 小时原生 1 分钟 K 线。

## 持久化与采集

- 迁移 0096_contract_market 删除旧 BTC 策略 state/snapshot 表及专属任务记录。原策略任务、页面、首页概览和 BTC 现货预测后台采集退役。迁移不可逆，回滚需迁移前备份。
- futures_contract 存共享标的、分类及 `underlying_symbol`；默认 19 个由迁移插入（排除币本位 BTCUSD_PERP），空库 bootstrap 同样只执行一次 seed。后续删除不会在重启时恢复。
- 迁移 `0101_contract_underlying` 按已有合约代码、分类回填锚定标的，保留原列表及全部日线。空库 bootstrap 同样回填。新合约以交易所 `baseAsset` / `underlyingType` 为准（缺 baseAsset 时使用去除 USDT 后缀的合约代码），不信任客户端填写的锚定标的。
- `NVDAUSDT → NVDA.US`、`SOXLUSDT → SOXL.US` 等美股/ETF 复用完整现货证券详情；`BTCUSDT → BTC.CRYPTO` 等加密货币暂只展示行情与历史 K 线空态。商品、韩股、无法确认可用现货证券代码的交易所别名以 `.OTHER` 标识并同样展示空态，不调用股票行情或研究接口，也不把永续合约价格当成现货价格。既有分类推断不能确认时使用空态；后续可在数据库修正锚定代码。
- futures_daily_bar 存 UTC 已闭合日线（原生未复权），主键为合约与开盘毫秒时间戳。首次向前读取约五年，后续补齐到最近日；移除合约同时级联删除日线。
- 既有 Streamer leader 额外运行独立采集协程：24h ticker 与资金费率约 5 秒刷新、分钟线约 10 秒刷新、日线约 60 秒补齐。Redis 保存报价（60 秒 TTL）、近 1440 个自然分钟的窗口（24 小时 TTL，读取时按当前 24 小时边界裁剪）、当日预览（180 秒 TTL）；失败保留已有值直到过期，缺失不补零。24 小时窗口包含当前形成中的一分钟。数字价格和成交量按原生 K 线解析，不做前复权。
- 数据源为 Binance USD-M 公共 REST：/fapi/v1/exchangeInfo、/fapi/v1/ticker/24hr、/fapi/v1/premiumIndex、/fapi/v1/klines。可设置 BINANCE_FUTURES_REST_BASE_URL，默认 https://fapi.binance.com；无 API key。默认标的未上市、停牌或交易所不可用时保留列表，显示暂无行情。
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

WS 每 5 秒推送最新快照；interval 参数选择 1d 或 1m，避免重复传送非当前周期的 K 线；连续两次失败后使用 SSE，断开自动重连。前端不连接 Binance。
