# 持仓与 Trade Engine

数据库是普通股票/ETF 实际持仓的权威来源。Google Sheet 仍可连接，但只作为补充来源，后续主要用于复杂期权等外部持仓。Trade Engine 是**中线持仓管理引擎**，不是日内 Scanner，也不自动下单。

页面 `/market/holdings`。DB API `/api/v1/holdings`，Trade Engine `/api/v1/trade-engine`。Google OAuth 仍走 `/api/v1/holdings/google/*`。

## 数据模型

- `portfolio_account`：每个市场一个默认账户（A股账户/CN、美股账户/US）。不存 currency，货币由 `market` 推断。CN 与 US 的 cash / NAV / 仓位 / 风险必须分开计算，禁止混合。
- `portfolio_position`：当前实际持仓。V1 只支持 STOCK/ETF，数量单位是股（NUMERIC，兼容碎股），canonical symbol 如 `600519.SH` / `AAPL.US`。`trade_engine_enabled` 默认 true；关闭后该持仓不进入 quotes / daily / strategy / LLM。
- `position_lot`：CORE/ADDON 风险归因，不是税务 lot。第一次买入建 CORE，继续买入建 ADDON，卖出 newest ADDON → older ADDON → CORE。只要本轮 position 曾经有过 ADDON（即使 remaining=0），`add_v1` 视为已经加仓过。
- `trade_operation`：BUY/SELL 操作记录。日K BST 由此动态聚合，不另建 BST 表。
- `cash_operation`：DEPOSIT/WITHDRAW。买入/卖出的现金变化由 trade_operation 解释，不复制成 cash_operation。
- `holding_source`：Google OAuth 与 Sheet 快照配置。
- `trade_strategy_state`：按 `uid + account_id + position_id + strategy_key` 保存策略状态。
- `trade_signal`：正式发布的 BUY/ADD/REDUCE/EXIT。账户 Warning 用独立 key 入库但不作为用户交易信号展示。

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
- DB 没有的股票/ETF 可作为 `source=GOOGLE` 参与展示和 `exit_v1`。`add_v1` 不对 Google 外部持仓产生 ADD。
- OPTION 只作为 `EXTERNAL_ONLY` 外部持仓：不进 DB、不进 Trade Engine、主持仓页不展示期权字段。

LLM 自然语言上下文走 `render_portfolio_context()`，必须标记 `[DB]` / `[GOOGLE]`。

## Trade Engine 定位

Trade Engine 用于已有持仓管理、加仓、减仓、退出、未来买入和账户风险提醒。风格偏中线：不要因为盘中普通小波动、VWAP 短暂跌破或单根放量产生交易信号。

调度仍是每 5 分钟：

- `trade_engine_cn` / `trade_engine_us`

但 **Engine 调度频率 != Strategy 决策周期**。5 分钟主要用于检查最新报价是否触及已有保护条件，以及感知持仓/现金变化。中线 Strategy 主要基于日线、持仓成本、lot、高水位、趋势结构、ATR、仓位和风险预算。

```text
持仓事实
   ↓
多个中线 Strategy 独立并行提出明确交易 Proposal
   ↓
没有 BUY/ADD/REDUCE/EXIT
→ 无事发生

有 Proposal
   ↓
LLM + Web Search 最终裁决
   ↓
Final Trade Decision
   ↓
DB + Notification

Portfolio Risk
   ↓
独立 Warning
   ↓
直接通知
```

Universe 是 `PortfolioResolver.stock_positions()`：普通股票/ETF、数量>0，且 `trade_engine_enabled=true`。过滤发生在 quotes / daily / strategy / LLM 之前。

当前注册的 Position Strategies：

```text
exit_v1
add_v1
```

二者并行，共享不可变 `PositionContext` / `PositionRisk`，互不读取对方本轮 Proposal。冲突（例如 REDUCE 与 ADD 同时存在）全部交给 LLM，代码层不做 EXIT > REDUCE > ADD 丢弃。

BUY 作为数据结构保留，供未来 entry strategy 使用；当前不注册假的 `entry_v1`。

PATCH `/api/v1/holdings/positions/{id}` 只改当前用户的 DB position（`trade_engine_enabled`），不写 Google Sheet。

### Strategy Proposal

正式交易动作只有：

```text
BUY ADD REDUCE EXIT
```

Strategy 内部可以判断 HOLD/WATCH，但对引擎外部等价于无交易信号：不创建 Proposal、不调用 LLM、不入 `trade_signal`、不通知。没有 severity / hard / soft。

### exit_v1

负责 REDUCE / EXIT。使用完整日线形成 CORE/ADDON 独立保护：entry、high watermark、Stage A/B/C、capital stop、structure stop、profit protection stop；active stop 只能提高不能降低。Trade Engine 每 5 分钟用最新有效 quote 检查 `quote <= active stop`。仅 ADDON 触发时 REDUCE 到剩余 CORE；全部触发则 EXIT 到 0。

已删除全部 5 分钟 soft weakness：ordinary weak、severe break、EMA20/VWAP weakness、previous_30m_low、RVOL soft exit、weak/recovery streak、soft episode。

### add_v1

只对 DB STOCK/ETF 主持仓。同一根完整日线最多一次 Setup。亏损摊平、Stage C、过度扩张（Close-MA10 > 1.5 ATR）、已经有过 ADDON lot、现金/仓位/风险不足都不产生 ADD。

两个 Setup：

- `BREAKOUT_CONTINUATION`：整理 3~8 日后日线突破并放量。
- `PULLBACK_REENTRY`：曾有 >=5% 浮盈后的健康回踩，再收盘转强。

数量取仓位容量、风险容量、现金容量的最小值，再按整股合法化。Google 外部持仓不主动 ADD。

### LLM Resolver

有 Proposal 时按持仓一次调用 LLM。最终 action 必须属于本轮 Proposal 或 `NO_ACTION`。ADD/BUY 不能超过 Proposal 数量；REDUCE/EXIT 不能比退出 Proposal 更激进。Web Search 只辅助当前 symbol。`NO_ACTION` 不产生正式 TradeSignal，不发交易通知。

通知必须同时展示全部 Strategy Proposal 和 LLM 最终结论，即使某个 Strategy 未被采用。

### Portfolio Warning

`portfolio_risk_v1` 不是 Strategy Proposal。按当前 market/account 独立计算 max_symbol_weight、risk_per_symbol、max_gross_exposure、total_open_risk。直接通知，不交给 LLM。首次超限通知，持续超限不重复，恢复后 clear，再次超限使用新 episode key 再次通知。

## 调度

- `holdings_sync`：每 5 分钟，`ingestion` 队列。
- `trade_engine_cn` / `trade_engine_us`：对应市场真实交易时段每 5 分钟，`alerts` 队列；cron 为 `*/5`，task 内再用交易日历校验 session / 半天市 / 假期。

已删除：`portfolio_risk_cn/us`、`analysis_a_share_intraday`、`analysis_us_intraday`、`cn_position_intraday_v1`、`us_position_intraday_v1`。

Alembic head 为 `0062_holdings_portfolio_risk`。

## BST

股票日K：同一交易日只有 BUY → B，只有 SELL → S，两者都有 → T。点击/hover 显示当天操作。

BTC 不建真实账户。策略快照 `BUY→B`、`EXIT→S`，同一当前图表 interval bucket 同时出现则 T。按当前选中 strategy 筛选。UI 标明「策略 BST / Strategy Signal」，不是真实成交。

## 部署

1. 填写 `.env.example` 中的 Google OAuth 与 `GOOGLE_OAUTH_TOKEN_KEY`。
2. 重定向 URI 仍为 `.../api/v1/holdings/oauth/callback`。
3. 跑 Alembic 至 `0062_holdings_portfolio_risk`。
4. 普通 worker 已消费 `ingestion` 与 `alerts`。
5. 可选配置全局 Telegram/ntfy；没有渠道时引擎仍可用。
