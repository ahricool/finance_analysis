# 实时行情 Streamer

`finance-analysis-stream` 独立于 FastAPI / Celery 运行。采集池是所有用户自选股与未清仓持仓的去重并集，
从 PostgreSQL 只读加载；报价、分钟线、趋势、形态和观测事件只写 Redis，不写行情数据库。

## 两条独立采集链

- US（以及保留的 HK）：Longbridge 批量报价快照和 Quote 订阅，每批至多 100 只。
  SDK 的 1min K 线订阅／历史接口只接受单证券，保留这些必要的单证券调用。
  批量订阅前先注册标的归属，重连沿用 connection / symbol generation 防旧事件污染。
  历史预热限定最近交易日的常规交易时段。
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
午休/收盘继续拉取最终闭合线，缺失持续三分钟后降低至五分钟重试；不在休市持续高频请求。
一次整段预热仅计算最新状态，不逐根重放历史形态事件。形态观测时间仍为当前实际时间。

选型证据、easyquotation 调研、生产网络测试和复测命令见 [cn-minute-sources.md](cn-minute-sources.md)。

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
| rt:streamer:heartbeat | Hash | 全局及 CN 状态，TTL 30 秒 |

分钟只保留最近一个市场交易日，新日期写入时删除旧日期，迟到旧包不能补回旧日期。
Streamer 写入按交易日历设置 TTL，保留到下一交易日收盘后两小时，覆盖周末和长假。
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

GET /api/v1/market-data/intraday/{symbol}?since=<aware ISO time> 只允许本人自选或持有的 CN/US 证券。
首次／交易日变化返回 reset；CN 返回 full_snapshot=true 的完整当日窗口以传播切源及修订，US 后续返回 since 起的分钟更新；只读最近交易日分钟线和形态事件。
两张表复用同一展开组件：点名称保留详情，点普通单元格展开，按钮不触发展开。
仅展开时每 5 秒读取增量，收起或切市场后取消旧请求；图表时间使用上海／纽约时区。
右侧展示报价、趋势、形态、日内方向状态及分钟覆盖信息。CN 图显示昨收 0% 水平线及 09:30 / 15:00 时段边界，午休单独标识。
形态按首次实际观测时间画紧凑标记：红色 ▴ 为多、绿色 ▾ 为空、灰色 ◇ 为中性；不在图上绘制形态名称。
同一分钟仅显示最新观测事件的方向，点击后在图下查看保存的证据、阶段、参考位和失效位，并可切换该分钟的其他事件。
参考位／失效位线也仅在选中后显示，收起详情时移除；增量刷新保留选择，交易日重置或切换证券清除选择，不回画到形态拐点。
日内方向为 CN/US 公共计算，包含多空观察／确认／延续、失效、过期、休市和延迟；
不读取期权合约，交易窗口来自后端日历并支持美股半日市。

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
