# Binance Live Trade（USDⓈ-M USDT 永续）V1

## 只读运行边界

这是 Binance 正式账户监控，不是 Demo，也不是手动交易终端。
已选择的策略每 5 秒评估公共行情，无订单执行 transport、无前端交易按钮、无创建订单/撤单/平仓/改单/杠杆修改的 HTTP API。
开启 FA「自动交易」只保存本地状态；仍不会发送任何真实交易指令。
私有用户数据流的 listenKey 创建与续期是数据订阅管理，不是交易写操作。

公开合约行情独立；现有 Paper Trade 及其行为保持不变。Live 和 Demo 密钥、Redis 状态、PostgreSQL 表、账户和收益隔离。
Live REST 固定 `https://fapi.binance.com`，用户数据流 `wss://fstream.binance.com/private/ws/<listenKey>`。
只读 transport 采用精确的 method/path allowlist，交易、划转、提现及其他写操作在网络调用前拒绝，无 Live/Demo fallback。

## 配置和部署

在币安正式账户 API 管理中创建 HMAC 密钥，V1 只需要读取权限，不为测试验证交易权限，不申请提现权限。
服务端 `.env` 配置：

```dotenv
BINANCE_LIVE_API_KEY=
BINANCE_LIVE_API_SECRET=
```

不要复制 Demo 凭据或把密钥提供给浏览器/Git。正式环境现有 Compose 已挂载 `.env`。
代码合入并生成 SHA 镜像后，按现有流程在 `~/svr/finance_analysis` 执行 `bash deploy.sh`。
迁移 `0098_live_trade` 位于 Demo 0097 之后，新增四张独立表；另有 0099 单独保存按用户要求迁移的 Demo 总开关。Live 不修改原行情及 Paper Trade 交易逻辑。
首次配置密钥或修改密钥需要重启应用与 Trader（正常发布即可）。

管理员进入「加密货币 → Live Trade」，核对权益、余额和持仓与 Binance App 一致。
未配密钥不启动私有 reader，页面仍可读取本地开关；认证/同步失败显示实际状态。
首次读到账户 alias 时绑定该正式账户，使用其他账户的密钥时拒绝混合历史，保留旧数据并显示同步失败。

## 账户数据和开关

- Trader leader 独立启动只读监控协程，连接后以 REST 核对账户、余额、持仓、杠杆/保证金、普通/Algo 订单及收入流水。
  ORDER_TRADE_UPDATE 按真实交易所 ID 持久化订单/成交；账户和 Algo 更新触发 REST 核对。
  断线重连与周期性 REST 同步独立于浏览器和开关。
- 只显示 USDT 本位永续合约的持仓、订单及成交；账户总额是交易所 USD-M 返回值，多资产模式可能以 USD 计价。
  初次同步近期 7 天；增量重叠窗口补足，保存后持续积累。历史交易所保留期限、分页和可发现标的限制仍适用：
  已成交的外部标的由账户收入流水发现，当前挂单由账户级查询发现；
  首次连接之前已取消且无成交、且不在共享行情池的历史订单可能无法发现。
- 实际成交、手续费及资金费采用币安原始 Decimal 字符串，所有时间为 UTC；账户交易净收益汇总已同步 USDT
  REALIZED_PNL、COMMISSION、FUNDING_FEE，不计资金划转。首次没有有效同步数据时显示缺失。
- PostgreSQL `live_trade_control` 唯一账户开关，缺记录默认 false。管理员 PUT 写本地控制并在
  `live_trade_control_event` 同事务记录操作者 ID、变更时间、前后状态。GET 不写业务状态。
  `live_exchange_record` 与 `live_account_snapshot` 持久化实际历史和权益；Redis 只储存短期连接状态。
- 开关关闭时统一内部网关拒绝所有交易意图；不自动撤单、平仓或影响币安 App。
  已提交至币安的外部订单仍可能成交，FA 继续读取结果。
  开关开启时注册集合为空，继续只读。开关不会启用币安 API 权限。
- 管理员页面只提供本地开关、数据刷新及共享 K 线查看；交易操作仍使用币安 App/网站。

## 未来策略接口

`live_trade/gateway.py` 定义 `LiveIntent`、`Action`、空 `STRATEGIES` 注册边界和 `LiveGateway.submit`。
所有动作需要先读取数据库开关，读取失败或关闭一律拒绝；开启时未注册策略仍拒绝。
即使本地 mock 注册策略，V1 也返回 LIVE_EXECUTION_NOT_IMPLEMENTED，没有真实订单 transport。
后续实现接入前，需要独立审查账户交易权限、交易执行、风险检查及幂等；本版不包含任何策略逻辑或生产写入路径。

## 官方文档

- [USD-M General Info](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info)
- [USD-M User Data Streams](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/user-data-streams)
- [USD-M account REST](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account)
- [Binance Key 管理](https://www.binance.com/en/support/faq/detail/360002502072)

V1 默认离线测试以 MockTransport 校验生产 host 的读取、禁止写入、开关关闭/开启与已有仓位，真实凭据及交易请求均不参与开发、CI 或自测。

Strategy（0102）：管理员在 Live Trade 选择代码预设，每 5 秒读取共享公共行情进行信号观察。每次切换冻结账户权益并记录上一策略区间收益，归档见 `/crypto/strategy`。生产交易 transport 继续只读。
