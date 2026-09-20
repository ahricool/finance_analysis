# Google Sheet 持仓与分层风控

Sheet 是实际持仓的唯一编辑源。Finance Analysis 只读取 Accounts/Positions，不写回成交、不自动下单、不恢复旧 Portfolio CRUD。页面 `/market/holdings`，API `/api/v1/holdings`。本页风控是建议，不是回测或最优参数。

## 读取与身份

- Google OAuth Authorization Code + PKCE，scope 仅 `spreadsheets.readonly`。
- `state` 一次性；refresh token 用 `GOOGLE_OAUTH_TOKEN_KEY` Fernet 加密后存 `holding_source`。
- 只解析 spreadsheet ID 或 `docs.google.com` URL，不抓取用户提供的任意网址。
- 快照 `content_hash` 不含 `fetched_at`。Redis 丢失后，同源 hash 只重建缓存，不重置策略状态。
- 持仓 API 带 `Cache-Control: private, no-store`。全局通知不等于把持仓 API 或 OAuth 凭据公开。

## 分钟数据（仅 portfolio_risk）

实时报价继续走现有 REALTIME_QUOTES 顺序。其它业务默认 fallback 不变。

| 市场 | 5m 来源 | 接口 |
| --- | --- | --- |
| CN | `SinaMinuteProvider` | `ak.stock_zh_a_minute(symbol, period="5", adjust="")` |
| US | 现有 yfinance | `period=1mo` 冷启动，`period=5d` 刷新；`prepost=False` |

不要把新浪结果伪装成扶摇，不要把长桥或东财设为本模块隐式分钟 fallback，不要恢复全功能 AkShare、PyTDX、efinance、BaoStock。streaming 的 1m K 线不得改标签冒充 5m。

时间戳：

- 新浪按 **结束时间**：09:35 表示 09:30–09:35；15:00 表示 14:55–15:00。
- Yahoo 按 **开始时间**：未闭合行即使返回也不能推进策略。
- 只用已闭合 K 线；同一 `bar_end` 不重复累计确认。
- 请求完成时间不是行情时间，请求耗时不是行情延迟。
- 不写死 yfinance 一定延迟 15 分钟，也不声称它保证实时。

用户在某环境看到约 1970 根、42 个交易日只是实测记录，不是硬编码，也不保证所有股票/ETF 或盘中无延迟。首日不完整窗口不能当作完整历史日。缺 10 个完整交易日基准时 RVOL 为未知。

## 调度与缓存

- `holdings_sync`：每 5 分钟，`ingestion` 队列。
- `portfolio_risk_cn` / `portfolio_risk_us`：常规交易时段每分钟，`alerts` 队列；午休/非交易日跳过。
- 不新增 risk-worker，不把部署拓扑当功能前置条件。
- 5m 按 symbol/provider/timeframe/session/adjustment 共享 Redis 缓存；同一股票多条腿只请求一次。
- 报价硬保护不 round-trip 等待慢历史请求。新闭合 K 线有短发布缓冲和有界补查，失败保留原缓存并标 STALE。
- 不新增数据库分钟历史表。

## VWAP 与量能

`PORTFOLIO_RISK_VWAP_MODE=exact_or_proxy`（可改为 `exact_only`）：

- EXACT：真实成交额完整且单位可靠，`sum(amount)/sum(volume)`。
- PROXY：无真实成交额但 OHLC/量可靠，用 typical price。
- UNAVAILABLE：量不可靠、累计量为 0 或缺口；暂停依赖该指标的软规则，不偷偷删掉 VWAP 条件继续建议。

整个评估窗口统一一种口径。切换口径重置软确认计数，不重置已有减仓计划。页面、事件和通知展示 EXACT/PROXY/UNAVAILABLE。这是明确允许的近似，不宣称等同真实成交额 VWAP。

单个真实零量 bar 与连续异常零量分开；yfinance `volume=0` 保留 0。不能用盘前有价无量判断缩量或放量。

## 通知

复用现有 `NotificationService` 和全局 Telegram/ntfy。不建设私人通知系统，不要求用户先填私人渠道，不新增 Delivery 账本。

风控状态与 `risk_event` 同事务提交后调用 `push_existing`。`notification_id` 表示站内消息已记录；`push_sent` 只描述外推。已有 `notification_id` 的事件不因外推失败再次 `send()`。未配置渠道或外推失败不回滚风控。正常重复任务靠 episode/dedupe_key 去重；崩溃边界不做恰好一次投递承诺。

允许通知证券、数量、成本、CORE/ADDON、目标数量、保护价和必要风险证据。禁止 Google token、OAuth code/state、Sheet 私有标识和完整表格进入通知或日志。

## 策略主体

CORE/ADDON 独立保护基准，position 级统一软退出计划。加仓失败优先撤新增风险，不叠加对底仓再次减半。episode 与固定目标防止连续重复减仓。单票风险跨所有腿汇总。参数未经验证，不得称为已回测或已优化。

## 部署

1. 填写 `.env.example` 中的 Google OAuth 与 `GOOGLE_OAUTH_TOKEN_KEY`。
2. 重定向 URI 必须是 `.../api/v1/holdings/oauth/callback`。
3. 跑 Alembic 至 `0063_holdings_published_snapshot`。
4. 普通 worker 已消费 `ingestion` 与 `alerts`，无需新队列。
5. 可选配置全局 Telegram/ntfy；没有渠道时风控仍可用。
