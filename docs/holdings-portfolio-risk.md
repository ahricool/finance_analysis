# 持仓与 Trade Engine

数据库是普通股票/ETF 实际持仓的权威来源。Google Sheet 仍可连接，但只作为补充来源，后续主要用于复杂期权等外部持仓。Trade Engine 是**持仓级分析器**，不是全市场 Scanner。不自动下单，也不判断用户有没有执行建议。

页面 `/market/holdings`。DB API `/api/v1/holdings`，Trade Engine `/api/v1/trade-engine`。Google OAuth 仍走 `/api/v1/holdings/google/*`。

## 数据模型

- `portfolio_account`：每个市场一个默认账户（A股账户/CN、美股账户/US）。不存 currency，货币由 `market` 推断。
- `portfolio_position`：当前实际持仓。V1 只支持 STOCK/ETF，数量单位是股（NUMERIC，兼容碎股），canonical symbol 如 `600519.SH` / `AAPL.US`。
- `position_lot`：CORE/ADDON 风险归因，不是税务 lot。第一次买入建 CORE，继续买入建 ADDON，卖出 newest ADDON → older ADDON → CORE。
- `trade_operation`：BUY/SELL 操作记录。日K BST 由此动态聚合，不另建 BST 表。
- `cash_operation`：DEPOSIT/WITHDRAW。买入/卖出的现金变化由 trade_operation 解释，不复制成 cash_operation。
- `holding_source`：Google OAuth 与 Sheet 快照配置。
- `trade_strategy_state`：按 `uid + account_id + position_id + strategy_key` 保存策略状态。
- `trade_signal`：LLM 确认后的 WATCH/REDUCE/EXIT（硬保护可绕过 LLM）。一般 HOLD 不落库。

市值、仓位、浮盈亏按当前报价动态计算，不存 DB。

## 买卖与现金

同一事务：

- 入金/出金更新 `cash`，现金不能为负。
- BUY：写操作、创建/更新持仓、创建 CORE/ADDON、更新数量与剩余 lot 加权平均成本、`cash -= qty * price`。现金不足直接报错。
- SELL：数量不能超过当前持仓；newest-first 扣 lot；全部卖完后 `quantity=0` 且 `closed_at=executed_at`。再次买入开新一轮 position 和新的 CORE，不继承上一轮 Trade Engine 状态。

不考虑手续费。

## Google 与 DB

`PortfolioResolver` 合并 DB 与最新 Google 快照：

- 相同 `market + canonical symbol` 的普通股票/ETF：DB 存在则完全忽略 Google 数量/成本。
- DB 没有的股票/ETF 可作为 `source=GOOGLE` 参与展示和 Trade Engine。
- OPTION 只作为 `EXTERNAL_ONLY` 外部持仓：不进 DB、不进 Trade Engine、主持仓页不展示期权字段。

LLM 自然语言上下文走 `render_portfolio_context()`，必须标记 `[DB]` / `[GOOGLE]`。

## Trade Engine

Trade Engine 的 Universe 就是 `PortfolioResolver` 返回的当前有效持仓。没有持仓立即结束：0 LLM、0 signal、0 通知。

```text
Deterministic Strategy
        ↓
TradeSignalCandidate（WATCH / REDUCE / EXIT）
        ↓
无 Candidate → stop
有 Candidate → LLM Review
        ↓
CONFIRM → TradeSignal DB + Notification
REJECT  → 不入库、不通知
```

代码 registry：

```text
CN: ExitV1, CNPositionIntradayV1, PortfolioRiskV1
US: ExitV1, USPositionIntradayV1, PortfolioRiskV1
```

每次运行：解析当前持仓 → 只拉这些持仓的 quote/5m → 持仓级策略产出 Candidate → 有 Candidate 才 LLM 复核 → 确认后保存 signal/state 并通知。不扫描全市场，不调 web search，不自动下单。

`PositionContext` 只包含该持仓的报价、5m、指标、lot 与 strategy state。不计算全市场宽度、板块排名或 market regime。

`portfolio_risk_v1` 只对当前持仓输出仓位/风险 WATCH，不给卖出目标。CORE/ADDON、Stage A/B/C 留在 `exit_v1` 内部。

### exit_v1

保留硬保护、Stage A/B/C、high watermark、active stop、5m 普通走弱、严重破位、恢复、ADDON 失败优先退出。同一 soft episode 不重复减仓；用户卖出后按当前数量管理；恢复后可以新 episode。硬保护可随时给出更严格 EXIT，且不依赖 LLM。

### LLM Review

LLM 是 Reviewer，不是 Signal Generator。输入只有当前持仓、candidate、原因和有限 5m 摘要。输出 `CONFIRM` / `REJECT`。不能 BUY、不能加仓、不能把 target 提高到超过候选或当前持仓。硬保护不走 LLM，失败也不能挡住 EXIT 入库和通知。普通 soft candidate 在 LLM 失败时本轮不入库、不通知；同一根 5m 不再 review，下一根新完整 5m 仍满足时可再次 review。

## 分钟数据

实时报价继续走现有 REALTIME_QUOTES 顺序。Trade Engine 5m 来源：

| 市场 | 5m 来源 | 接口 |
| --- | --- | --- |
| CN | `SinaMinuteProvider` | `ak.stock_zh_a_minute(symbol, period="5", adjust="")` |
| US | 现有 yfinance | `period=1mo` 冷启动，`period=5d` 刷新；`prepost=False` |

不要把新浪结果伪装成扶摇，不要把长桥或东财设为本模块隐式分钟 fallback。只用已闭合 K 线。新浪按结束时间；Yahoo 按开始时间。

## 调度

- `holdings_sync`：每 5 分钟，`ingestion` 队列。
- `trade_engine_cn` / `trade_engine_us`：对应市场真实交易时段每 5 分钟，`alerts` 队列；cron 为 `*/5`，task 内再用交易日历校验 session / 半天市 / 假期。
- 已删除：`portfolio_risk_cn/us`、`analysis_a_share_intraday`、`analysis_us_intraday` 及其任务包。
- 保留：A 股收盘前复核、美股盘前/盘后、ETF/Trend preview、市场情绪、行业强度。

不新增专用 worker。Alembic head 为 `0062_holdings_portfolio_risk`。

## BST

股票日K：同一交易日只有 BUY → B，只有 SELL → S，两者都有 → T。点击/hover 显示当天操作。

BTC 不建真实账户。策略快照 `BUY→B`、`EXIT→S`，同一当前图表 interval bucket 同时出现则 T。按当前选中 strategy 筛选。UI 标明「策略 BST / Strategy Signal」，不是真实成交。

## 部署

1. 填写 `.env.example` 中的 Google OAuth 与 `GOOGLE_OAUTH_TOKEN_KEY`。
2. 重定向 URI 仍为 `.../api/v1/holdings/oauth/callback`。
3. 跑 Alembic 至 `0062_holdings_portfolio_risk`。
4. 普通 worker 已消费 `ingestion` 与 `alerts`。
5. 可选配置全局 Telegram/ntfy；没有渠道时引擎仍可用。
