# 实时行情 Streamer

`finance-analysis-stream` 独立于 FastAPI / Celery 运行。采集池是所有用户自选股、未清仓持仓与日内期权观察池（PostgreSQL `us_nasdaq100` 成分股去重 `GOOG.US` + `SPY/QQQ` 基准，约 102 只，含移出观察池但尚未平仓的旧标的）的去重并集，
从 PostgreSQL 只读加载；报价、分钟线、趋势、形态和观测事件只写 Redis，不写行情数据库。

## 两条独立采集链

- US（以及保留的 HK）：Longbridge 批量报价快照和 Quote 订阅，每批至多 100 只。
  SDK 的 1min K 线订阅／历史接口只接受单证券，保留这些必要的单证券调用。
  批量订阅前先注册标的归属，重连沿用 connection / symbol generation 防旧事件污染。
  US 分钟订阅及历史回补用 `TradeSessions.All`，包含盘前、盘中、盘后与夜盘；HK 仍仅常规交易时段。
  夜盘报价默认开启（`LONGBRIDGE_ENABLE_OVERNIGHT=true`），实际分钟覆盖取决于标的、交易日及长桥权限；Yahoo 降级仅尽力提供盘前/盘后。
- CN 报价：交易日常规时段以 5 秒为目标周期，经 MarketDataService 请求整个采集池，限定 Fuyao Provider；扣除本轮耗时，至少等待1秒，不并发重叠请求。
  股票、指数按 100 只分批，ETF 保留接口要求的单标的请求；轮询不叠加未完成轮次。
  没有浏览器连接也继续采集；午休、假期和收盘后不生成新分钟。
  Longbridge 重连不阻塞 CN 采集池更新和轮询，心跳另外报告 CN 健康状态。

ETF 接口于 2026-10-21 使用生产密钥只读实测：单 thscode 返回 code=0；
thscodes=510300.SH,510500.SH 返回 1001（缺少 thscode）；
thscode=510300.SH,510500.SH 返回 1002（每次只允许一个代码），不支持批量。
可显式复测（此脚本不属于离线测试）：

```bash
uv run python scripts/check_fuyao_etf_protocol.py --env /path/to/backend.env
```

## A 股原生分钟线

CN 分钟线独立于报价轮询：新浪免费 1min OHLC 为主源，腾讯 m1 为唯一 fallback，均经 MarketDataService。
每 15 秒刷新当日窗口，每源全进程最多 1 QPS、共享 3 个 worker，每批最多 20 标的轮转；失败不反复重试主源。
空响应、无效量价、超时或陈旧闭合线触发备用；两源失败保留旧数据及真实时间，不恢复报价采样或增加第三源。
北交所仅新浪已验证，腾讯返回空不伪造分钟线。Fuyao 报价仍独立采集。

分钟结束标签转为 UTC 开始时间，午休不生成 K 线，闭合/未闭合分别保存；预热与后续轮询整段替换当天来源窗口。
新浪提供股数和成交额；腾讯科创板量为股，其余沪深股票/ETF/指数由手换股，缺少成交额保持 null。
启动清理旧采样线与对应指标；新的原生缓存可恢复，缺失分钟不补造，缺口中断正式指标窗口，午休不算缺口。
午休/收盘核对开盘以来全部已闭合分钟，有缺口就继续请求整段，缺失持续三分钟后降低至五分钟重试；不在休市持续高频请求。
一次整段预热仅计算最新状态，不逐根重放历史形态事件。形态观测时间仍为当前实际时间。

选型证据、easyquotation 调研、生产网络测试和复测命令见 [cn-minute-sources.md](cn-minute-sources.md)。

## US/HK 重启与重连预热

US 每次订阅预热（含重启、重连）请求最近24小时全时段原生1min，长桥历史按最多1000根分页；即使常规时段缓存齐全仍检查扩展时段。HK 仍从交易所开盘逐分钟核对至最近已闭合的正常交易分钟。正常交易分钟按真实交易日历校验；非交易、无成交或缺线不填造。
HK 常规时段全段齐全即复用 Redis；US 则总是检查扩展窗口。应有常规分钟缺失、未确认、partial、sampled 或 OHLC 无效时，经 MarketDataService 进行历史校验和降级。常规分钟优先采用单一来源的完整区间；US 降级时同时保留主源可用扩展分钟。各来源都缺线时，保留已校验的分钟，按来源顺序补充缺口。
合并 Redis 和已收到的推送后，仍缺失的分钟继续标为缺口。只有上一交易日已闭合的最后一分钟可以校正报价昨收。

每个标的按分钟起始时间合并历史与推送，US 闭合分钟线最多1440根、严格滚动24小时，最新形成中K线独立保存；CN/HK 保持最近交易日。交易时段保存在 K 线内容里。Redis 可读取旧的“时间戳:时段”成员；下次写入时在同一事务内将其归并为时间戳成员并裁剪。

## Redis 与保留范围

| Key | 类型 | 内容 |
| --- | --- | --- |
| rt:quote:{symbol} | Hash | 报价、市场日期、上游时间、接收时间、来源 |
| rt:candle:1m:{symbol}:current | Hash | 最新分钟及闭合标志 |
| rt:bars:1m:{symbol}:index / :data | Sorted Set / Hash | 闭合分钟索引与内容 |
| rt:trend:1m:{symbol} | Hash | 均线方向与连续根数 |
| rt:pattern:1m:{symbol} | Hash | 正式形态与未闭合线预览 |
| rt:pattern:1m:{symbol}:events | Hash | 首次观测的形态阶段证据，幂等且不覆盖 |
| rt:subscription:{symbol} | Hash | 采集／预热状态 |
| rt:streamer:heartbeat | Hash | 全局及 CN 状态，TTL 30 秒，trading_owner=trader |
| rt:bars:1m:{symbol}:revision | String | 与闭合分钟数据同事务提交的 revision，供 Trader 增量缓存 |

US 分钟线跨午夜保留，写入时按 UTC 时间裁剪，另每分钟清理过期分钟；分钟相关 key TTL 不超过24小时，迟到包不能恢复已超出窗口数据。CN/HK 分钟线仍只保留最近一个市场交易日，新日期写入时删除旧日期。
报价、趋势、形态及 CN/HK 分钟按交易日历设置 TTL，保留到下一交易日收盘后两小时，覆盖周末和长假。
形态事件也随新日期清理。删除出整个采集池的标的缓存保留两小时后到期。
TTL 仅用于清理，不代表行情有效期。保留上游时间和接收时间，拒绝未来异常时间；
不将接收时间冒充上游时间。前端日内方向每秒更新判断时钟，行情时间与接收时间相对判断时间均允许 ±30 秒（含边界）；
落后超过30秒显示“行情延迟”，领先超过30秒显示“行情超前”，缺少可靠时间显示“时间异常”，均暂停方向判断。
分钟趋势的 bar_time 是已完成分钟的起始时间，单独保留180秒新鲜度窗口，超出显示“趋势更新延迟”。
后端报价展示字段 quote_status 的90秒门槛独立保留，不作为前端方向判断时钟。

## 页面读取与展开图

自选股／投资组合实时表格、展开分钟图及其 WS / SSE、持仓汇总只读 Redis 报价，缓存缺失不触发外部报价请求。
个股详情的日 K 查询独立于 Streamer 采集池：后端读取多日历史，再通过 MarketDataService 请求该股当天报价，
以 OHLCV 生成临时日 K，按交易日期去重拼接返回；CN 使用 Fuyao→Longbridge，US 使用 yfinance→Longbridge。
报价不可用时保留已有历史；未开盘、非交易日或查询范围不含当天时不请求临时日 K，不写入数据库或 Redis。
个股报价接口仍沿用现有缓存读取；后台策略保留自己的行情读取策略。
读取前按用户、市场与分组过滤；holdings scope 同时返回本人持仓估值及对应行情指标。
WS 每轮完成后等待 5 秒；连续两次连接／快照超时后浏览器固定回落 SSE。
SSE 等待时每 10 秒发送心跳，重连按 5/10/20/30 秒退避；鉴权失败停止。

GET /api/v1/market-data/intraday/{symbol}?since=<aware ISO time> 支持本人自选或持有的 CN/HK/US 证券及日内期权模拟共享观察池。
首次返回 reset。CN 和 HK 在交易日变化时 reset，并返回 full_snapshot=true 的完整当日窗口以传播切源及修订。US 返回最近24小时最多1440根分钟（包含最新形成中K线），跨日期不重置，后续按 since 返回增量；客户端回传 history_version，滚动淘汰、补回缺失分钟或修订已有 K 线时返回完整快照。每根 US K 线返回 `trade_session=pre|regular|post|overnight`，优先源标记，缺失时按纽约时区和交易所日历推断，前端用橙/中性/蓝/紫时段区分，提示框显示时段并提供「查看完整24小时」；美股形态事件按实际观测时间保留最近24小时。
两张表复用同一展开组件：点名称保留详情，点普通单元格展开，按钮不触发展开。
展开的分钟图在进入视口或邻近区域时开始每 5 秒刷新。离开该区域、收起或切市场时取消旧请求。图表按标的使用上海、香港或纽约时区。
右侧展示报价、趋势、形态、日内方向状态及分钟覆盖信息。CN 图显示昨收 0% 水平线及 09:30 / 15:00 时段边界，午休单独标识。
形态按首次实际观测时间画紧凑标记：红色 ▴ 为多、绿色 ▾ 为空、灰色 ◇ 为中性；不在图上绘制形态名称。
同一分钟仅显示最新观测事件的方向，点击后在图下查看保存的证据、阶段、参考位和失效位，并可切换该分钟的其他事件。
参考位／失效位线也仅在选中后显示，收起详情时移除；增量刷新保留选择，交易日重置或切换证券清除选择，不回画到形态拐点。
实时趋势与形态从最近最多120根连续有效分钟线计算。美股盘前、盘中、盘后、夜盘和合约跨午夜均可延续窗口。A股、港股午休前后的相邻交易分钟可衔接。均线目标20根，从首根开始给出参考值并标明覆盖，满5根可判断方向。形态的量价基准取最近20根。CN/US 日内方向全天检查报价、趋势和形态的时间，行情停更时显示延迟。

## 运行与验证

```bash
uv run finance-analysis-stream
uv run pytest tests/market_stream tests/test_realtime_market_websocket.py -q
cd web
pnpm exec playwright test e2e/intraday-streamer.spec.ts
```

REALTIME_REDIS_URL 留空时回退 REDIS_URL，读写两侧保持一致。凭证沿用 LONGBRIDGE_* 和 FUYAO_API_KEY。
其余频率和容量由 MarketStreamConfig 定义，并非任意 MARKET_STREAM_* 环境变量。
使用 lock:market_stream:leader 保证单写者，失锁退出；正常部署仍使用生产目录的 bash deploy.sh。

## 日内期权观察

固定US观察池额外纳入Streamer，独立 Trader 从 Redis 读取闭合分钟线并计算15/30/60分钟趋势质量分及独立日内机会，只存Redis最新结果，不归档历史。
页面 `/market/intraday-options` 只读缓存；共享分钟接口允许已登录用户读取该固定白名单，不修改个人自选。见 [intraday-options.md](intraday-options.md)。

日内策略、Demo/Live 账户与执行独立运行于 Trader，见 [Trader](trader.md)。
