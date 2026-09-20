# 持仓与 Trade Engine

数据库是普通股票/ETF 实际持仓的权威来源。Google Sheet 仍可连接，但只作为补充来源，后续主要用于复杂期权等外部持仓。Trade Engine 只分析和建议，不自动下单，也不判断用户有没有执行建议。

页面 `/market/holdings`。DB API `/api/v1/holdings`，Trade Engine `/api/v1/trade-engine`。Google OAuth 仍走 `/api/v1/holdings/google/*`，并保留旧路径别名。

## 数据模型

- `portfolio_account`：每个市场一个默认账户（A股账户/CN、美股账户/US）。不存 currency，货币由 `market` 推断。
- `portfolio_position`：当前实际持仓。V1 只支持 STOCK/ETF，数量单位是股（NUMERIC，兼容碎股），canonical symbol 如 `600519.SH` / `AAPL.US`。
- `position_lot`：CORE/ADDON 风险归因，不是税务 lot。第一次买入建 CORE，继续买入建 ADDON，卖出 newest ADDON → older ADDON → CORE。
- `trade_operation`：BUY/SELL 操作记录。日K BST 由此动态聚合，不另建 BST 表。
- `cash_operation`：DEPOSIT/WITHDRAW。买入/卖出的现金变化由 trade_operation 解释，不复制成 cash_operation。
- `holding_source`：Google OAuth 与 Sheet 快照配置。
- `trade_strategy_state`：按 `uid + account_id + position_id + strategy_key` 保存策略状态。
- `trade_signal`：可通知的 WATCH/REDUCE/EXIT/WARNING；一般 HOLD 不落库。

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
- OPTION 只作为 `EXTERNAL_ONLY` 外部持仓：不进 DB、不进 `exit_v1`、主持仓页不展示期权字段。

LLM 自然语言上下文走 `render_portfolio_context()`，必须标记 `[DB]` / `[GOOGLE]`。

## Trade Engine

代码 registry，不是插件框架：

```text
CN: ExitV1, CNIntradayV1, PortfolioRiskV1
US: ExitV1, USIntradayV1, PortfolioRiskV1
```

每次运行：解析当前持仓 → 该市场构建一次 MarketContext → 批量报价/5m → 执行策略 → 聚合信号 → 保存必要 state/signal → 首次或升级事件通知。不调 LLM，不自动下单。

聚合极简：`EXIT > REDUCE > WATCH > HOLD`；多个 `suggested_target_quantity` 取最小值。`portfolio_risk_v1` 只输出 WARNING，不算应该卖哪一只。CORE/ADDON、Stage A/B/C 留在 `exit_v1` 内部。

### exit_v1

保留硬保护、Stage A/B/C、high watermark、active stop、5m 普通走弱、严重破位、恢复、ADDON 失败优先退出。同一 soft episode 不重复减仓；用户卖出后按当前数量管理；恢复后可以新 episode。硬保护可随时给出更严格 EXIT。

### MarketContext

一个 market / 一次 run 只构建一次，所有持仓共享。CN 复用已持久化的市场结构、情绪、行业观察；US 复用已持久化的市场结构。不恢复全市场盘中选股 scanner / LLM Judge。

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
- 已删除：`portfolio_risk_cn/us`、`analysis_a_share_intraday`、`analysis_us_intraday`。
- 保留：A 股收盘前复核、美股盘前/盘后、ETF/Trend preview。

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
