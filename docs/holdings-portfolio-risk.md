# 持仓与 Trade Engine

数据库是普通股票/ETF 实际持仓的唯一事实源。Trade Engine 是**中线持仓决策系统**：Strategy 机械地重新描述当前发生了什么，LLM 记住过去并决定整个 A 股或美股账户最终应该持有什么仓位。不自动下单。

页面 `/market/holdings`。DB API `/api/v1/holdings`，Trade Engine `/api/v1/trade-engine`。

```text
                 DB Portfolio
                 唯一持仓事实源
                        │
                        ▼
              Market Portfolio Context
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
    Position Facts   Market Data    Trade History
        │          15d Daily + Today      │
        │               OHLCV             │
        └───────────────┬─────────────────┘
                        ▼
              Stateless Strategies
              ├─ exit_v1
              ├─ add_v1
              └─ entry_v1（未来）
                        │
                        ▼
                 Strategy Signals
                        │
              Portfolio Risk Facts
                        │
             Previous LLM State
                        │
             One Market-level LLM
                  + Web Search
                        │
               Target Positions
                        │
            Mechanical Validation
                        │
         BUY / ADD / REDUCE / EXIT
              ┌─────────┴─────────┐
         TradeSignal          LLM State
         Notification           Update
```

CN / US 分别独立执行。

## 数据模型

- `portfolio_account`：每个市场一个默认账户。CN 与 US 的 cash / NAV / 仓位 / 风险 / LLM 状态必须分开，禁止混合。
- `portfolio_position`：当前实际持仓。V1 只支持 STOCK/ETF。`trade_engine_enabled` 默认 true；关闭后该持仓不运行 Strategy，LLM target 强制等于 current，但仍计入账户 NAV、仓位和风险。
- `position_lot`：CORE/ADDON 风险归因。第一次买入建 CORE，继续买入建 ADDON。只要本轮 position 曾经有过 ADDON（即使 remaining=0），`add_v1` 视为已经加仓过。
- `trade_operation`：BUY/SELL。日K BST 由此动态聚合。
- `cash_operation`：仅保留历史 DEPOSIT/WITHDRAW 记录，新操作不再写入。
- `trade_llm_state`：每个 `uid + market` 一行。保存简洁交易记忆 `summary` 和上一轮 `last_decision`。
- `trade_signal`：仅在 LLM 最终 `target ≠ current` 时写入 BUY/ADD/REDUCE/EXIT。

市值、仓位、浮盈亏、high watermark、Stage、active stop 全部本轮重算，不作为 Strategy state 持久化。

## 买卖与现金

同一事务：

- 通过 `PATCH /api/v1/holdings/cash` 按账户设置独立现金余额（可为 0，不可为负）。移除入金/出金入口；现金仅供 NAV、仓位、Trade Engine 与风险计算，买卖不自动改变现金，也不以现金余额限制买入录入。已有现金值原样保留。
- BUY：写操作、创建/更新持仓、创建 CORE/ADDON、更新数量与剩余 lot 加权平均成本；不修改现金。买入复用证券搜索建议，并由后端校验 instrument 中的代码、市场及 STOCK/ETF 类型，以主数据类型为准。
- SELL：数量不能超过当前持仓；newest-first 扣 lot；全部卖完后关闭当前 position。再次买入开新一轮。

不考虑手续费。

## Trade Engine 定位

Beat 每 30 分钟触发 `trade_engine_cn` / `trade_engine_us`。任务内再用交易日历判断 evaluation window：不在窗口则 skip。不要把调度频率理解成日内高频止损系统。

Strategy 主要基于持仓事实、Lot、完整日线、中线结构、当前实时报价和 Portfolio Risk。今日盘中 OHLCV 同时给 LLM 作上下文；`add_v1` 在自己的局部 evaluation bars 中使用今日临时 K。

日线通过 `MarketDataService.get_daily_bars(..., source_policy="db_latest")` 读取，并过滤 `trade_date <= latest_completed_trading_day`。Strategy / PositionRisk 历史覆盖 `min(lot.entry_time) - 30 calendar days` 到最新完整交易日，不能为了 15d LLM 窗口截断 high watermark。LLM 只看到最近 15 根完整日 K。

## Stateless Strategy

`exit_v1` / `add_v1` 不保存、不读取任何 state。同样输入得到同样输出。每 30 分钟重复相同 REDUCE/ADD 是正确行为。

- `exit_v1`：从 Position + Lots + 完整日线重算 lot high watermark、Stage A/B/C、capital / structure / profit stop，`active_stop = max(...)`。有效报价 `<= active_stop` 则 REDUCE 或 EXIT。
- `add_v1`：历史完整日K + 今日临时K判断 BREAKOUT_CONTINUATION / PULLBACK_REENTRY。临时K日期取市场当地日期，O/H/L/volume 来自实时行情，C 为实时现价；只保留今日之前的完整历史，避免同日重复。所有 sizing（市值、仓位容量、风险和现金容量、建议入场价）使用该实时现价。MarketData 负责数值清洗与质量校验；Trade Engine 只检查报价、正价格、时间存在与 stale。ADD 信任标准 DTO，仅要求报价 valid/non-stale、OHLCV/时间齐全且属于当前市场当地日期，不重复检查 finite/OHLC 范围，不以昨日 close 替代。Streaming quote_time 使用 event_time 或 received_at，两者相同也有效。成功 realtime MarketQuote 必须有 UTC 时间：优先 provider 行情时间，缺失时使用 snapshot 获取时间；yfinance fast_info 直接使用 fetched_at，Longbridge/Fuyao 在 provider timestamp 缺失时回退获取时间，不增加额外请求。
- 临时K只在 ADD 内存副本中使用，不进入 PositionRisk、EXIT high watermark/stage/stop，也不持久化。今日成交量是盘中累计量；突破仍保守要求累计量已经达到完整日历史中位量门槛，不预测全日量，早盘可能不发信号。回踩的缩量判断仍使用之前的完整日K。evidence 标注临时K和成交量口径。
- 本轮不实现 `entry_v1`。没有 BUY Strategy Signal 时 LLM 不能凭空新开仓。

Strategy Signal 只存在于本轮内存，作为 LLM 输入。正式调仓时写入 TradeSignal evidence 便于审计。

## Portfolio Risk Facts

`portfolio_risk_v1` 每轮计算 NAV、cash、gross exposure、单票权重/open risk、总 open risk 及 policy limits。这些是客观事实，不直接通知，全部交给 LLM。

## Market-level LLM

每个市场每轮最多一次 LLM。只要该市场存在实际持仓就调用，即使本轮没有 Strategy Signal。空仓且没有 Entry Strategy 则 skip。

增加仓位必须有对应 BUY/ADD Strategy Signal，且不能超过机械允许的最大 ADD。降低仓位可以因为 exit_v1、Portfolio Risk 或重大实时风险。disabled position 的 target 必须等于 current。

LLM 主要输出 target_quantity。代码按 current vs target 派生 BUY/ADD/REDUCE/EXIT/NO_ACTION。`target == current` 不创建 TradeSignal、不发通知，但仍更新 `trade_llm_state`。

Web Search 仅限当前市场已有持仓的重大公司事件。CLI backend 不支持真实搜索时标记 `web_search_available=false`，不得声称已经检索。

## 串行决策与通知去重

`evaluate_uid` 统一保护 scheduled / manual 两个入口。复用 PostgreSQL session advisory lock，稳定双整数 key 为 `(CN:20260921 / US:20260922, uid)`，不使用 Python hash。try-lock 失败立即返回 `SKIPPED_LOCKED`，不同市场/用户不互锁。锁覆盖持仓/行情/历史/state 读取、策略、风险计算、LLM、结果事务与提交后 push；异常也释放。锁连接 acquire 后立即 commit，不保持业务事务。

读取 state / recent signals 使用短 session 并转为 DTO 后关闭；LLM/Web Search 在 session 外执行；随后短事务更新 state、写 TradeSignal 和 Notification，commit 后 push。

LLM Prompt 要求综合当前现金及所有加仓合计支出、总/单票仓位和风险预算，竞争预算时主动取舍，超限时优先降风险。这些是建议约束，执行由用户决定；代码仅保留原有 target 非负、disabled 固定、增加必须有机械信号且不超过上限的边界，不增加组合硬优化。

LLM 结合 previous state/decision、recent signals、真实持仓、行情和重大新闻判断重复建议价值；无实质变化优先 NO_ACTION，风险恶化允许再次建议。

正式 TradeSignal 仍可保存重复决策。通知只包含当日未通知的 `(uid, market, symbol, action)`，只查询 `notification_id IS NOT NULL` 的信号；其余历史信号 notification_id 为空。全部重复则不创建消息、不 push，但策略/LLM/state 更新照常。日期使用市场当地日（CN Asia/Shanghai，US America/New_York），查询当地午夜到次日午夜的 UTC 半开区间，兼容 DST。通知意味着站内消息已持久化，不表示外部渠道成功送达。

## 调度

- `trade_engine_cn` / `trade_engine_us`：每 30 分钟，`alerts` 队列；cron 为 `*/30`，task 内再用交易日历校验 session / 半天市 / 假期。

Alembic head 为 `0062_holdings_portfolio_risk`。

## BST

股票日K：同一交易日只有 BUY → B，只有 SELL → S，两者都有 → T。

## 部署

1. 跑 Alembic 至 `0062_holdings_portfolio_risk`。
2. 普通 worker 已消费 `alerts`。
3. 可选配置全局 Telegram/ntfy；没有渠道时引擎仍可用。
