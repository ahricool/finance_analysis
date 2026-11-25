# Binance USDⓈ-M Paper Trade（官方 Demo Trading）

## 范围与启动

Paper Trade 是独立的管理员功能。币安 Demo 是余额、持仓、订单、成交和流水的事实源；
FA 不模拟撮合、不生成虚拟本金、不接入 Live，不提供现货、币本位、充值、提现、划转、重置资金或账户模式/杠杆修改接口。

1. 在币安 App 确认已开通 Demo Trading；进入同一 Demo Trading 账户的 API 管理页面创建 Demo API Key（HMAC 类型），按需授予 Demo 合约交易权限。
2. 在服务端 `.env` 设置：

   ```dotenv
   BINANCE_DEMO_API_KEY=
   BINANCE_DEMO_API_SECRET=
   ```

   将密钥值填入服务端文件，不放入 WebUI、Git 或日志。REST 固定为
   `https://demo-fapi.binance.com`，私有流固定为 `wss://demo-fstream.binance.com/private/ws/<listenKey>`。
   不接受交易 URL override，也不回退生产交易接口。
3. 正常发布（生产项目目录 `~/svr/finance_analysis`，`bash deploy.sh`），或在本地执行
   `uv run alembic upgrade head` 并启动 API 与 Streamer。现有 Compose 已挂载服务端
   `.env`，无需新增容器、Celery 任务或队列。迁移 `0097_paper_trade` 新建四张独立表；不触碰合约行情、旧 BTC 策略或真实股票持仓。
4. 管理员进入「加密货币 → Paper Trade」，等待 REST 账户、余额、持仓与历史核对。
   对照 App 的权益、钱包余额、可用余额及持仓，确认同一账户。连接校验不会提交订单。
   账户 alias 在首次读取时在任何成交写入前绑定；同一账户换 Key 可以继续核对，不支持切换到另一账户并混合历史。

密钥配置后账户同步自动运行。管理员在页面使用独立「Demo 交易总开关」，数据库默认 false（迁移 0099）。
所有创建的策略默认暂停；只有总开关开启且实例启用才新增自动仓位。关闭总开关阻止新开仓意图、取消待提交开仓队列，
不取消现有交易所订单、也不平仓；撤单、减仓/平仓、既有保护单和风险管理继续。重新启用不补做旧 K 信号。
停止账户连接需要移除密钥并重启 Streamer；不自动撤销币安端订单。
公开合约行情独立运行，Demo 配置缺失、认证失败、网络中断时不影响公共行情。

## 手动验证

页面无预填交易合约、方向及数量。选择 Demo 目录中的合约，填写数量，根据订单类型填写限价或触发价，
核对弹窗后提交。支持普通 MARKET/LIMIT 及独立 Algo STOP_MARKET/TAKE_PROFIT_MARKET。
撤单必须选择交易所实际可撤销订单；平仓确认冻结所见数量及开仓均价，若持仓已变化则要求重新确认；实际使用单向持仓模式下的 reduce-only 市价订单。
初版仅支持单向持仓（One-way mode）交易，双向持仓仍可读；自动策略的“双向”表示可持有单一净多或净空，
不是同时持有双边仓位。杠杆/保证金模式由 App 设置并读取，FA 不自动修改。

HTTP 202 表示意图已持久化、等待 Streamer 执行；交易所 ACK 不代表成交。网络超时/不确定结果
保存 UNKNOWN，并按固定 client order ID 核对，绝不盲目重复写订单。存在未解决订单时阻止该合约新增交易。
条件单 FINISHED 只代表触发后的订单生命周期结束，实际成交另以成交记录确认。
浏览器只轮询 FA 管理员 API，不连接币安私有接口。

## 自动策略

配置策略名称、共享行情标的、策略类型及对应参数、允许方向、名义额度、计划保证金、杠杆上限、
最大名义持仓、最大亏损及止损比例；保存后默认暂停。每个合约一个实例。
只有确认启用实例且 Demo 交易总开关开启后，Streamer 才可以自动开仓；暂停只禁止新增仓位，保留交易所已有保护单，并继续管理已有 FA 仓位的反向退出与亏损限制；不接管 App 手动持仓。
若要退出 FA 管理仓位，先暂停或使用持仓平仓按钮（自动暂停该策略），然后核对普通/条件订单。

首个注册策略是 UTC 对齐的已闭合 5 分钟快慢 EMA 交叉。预热要求连续分钟数据，
剔除形成中的分钟线，距离信号形成超过 90 秒不执行；每策略每闭合 K 一次，重启/断线恢复不补交易历史信号。
生产 Redis 1m 仅用于研究信号，订单基于 Demo 目录、交易状态、报价、账户、交易规格、杠杆与额度；
研究收盘价与 Demo 报价偏离超过 2% 阻止自动开仓。TradFi 另读取 Demo tradingSchedule，
无法确认实际交易时段时不下单。不存在生产交易接口 fallback。

已有 FA 净仓位必须由实际成交记录关联且与 Demo 净仓位一致；存在外部订单、外部成交干预或无法对账的
仓位时阻止自动接管。反向交叉只退出，不同一根 K 反手。止损为独立的 reduce-only Algo 条件单；
风险达到配置亏损上限可提交 reduce-only 平仓。止损不是成交价格保证，Demo 也可能跳价、拒单或部分成交。
策略仅用于验证订单闭环，不用于评估策略收益率。

### 24/7 永续驱动（V8）

新增独立策略 `perpetual_drive`，源于当前日内期权 V8 开盘纯净驱动；源码在
`paper_trade/strategies/perpetual_drive.py`，不调用日内期权策略或依赖美股交易日历。
保留 EMA 验证策略及原有 Demo 执行、仓位归属、全局开关。Live 不注册此策略。

- 无自然开盘：每个 UTC 整点冻结一个新的前 5 分钟高低点，最近两个窗口重叠；
  每个窗口仅在已闭合第 15、20、…、115 分钟检查，首次满足条件才产生新信号。
  两个窗口同时第一次满足时取较新的窗口。历史前缀只用于确认该窗口尚未产生信号；
  断线或暂停期间错过的信号不会在恢复后补单。周末及 UTC 午夜正常评估，没有强制日终平仓。
- V8 参数：初始 5m 振幅 ≥0.8%，收盘突破冻结高低点、方向涨跌幅 ≥1.2%、路径效率 ≥0.48，
  最后一根 1m K 方向一致且位于真实成交额/成交量 VWAP 的同侧；首分钟超过 3% 的异常影线回缩至实体。
  BTCUSDT 同窗口方向涨跌幅 ≥0.15% 且与 BTC VWAP 同侧，非 BTC 标的相对强度 ≥0.8%。
  去掉美股隔夜跳空、SPY/股票池宽度和领涨排名；BTC 自身不与自己比较相对强度。
  振幅、涨跌幅、路径效率、相对强度可在前端独立配置；这些是研究初始值，不是经过合约收益验证的参数。
- 仅支持 Demo 目录 `underlyingType=COIN` 的 USDT 永续；BTCUSDT 必须保留在共享行情池。
  本标的、BTC 原生分钟线缺失/断档/过期，或冻结窗口前 15 个连续 UTC 已闭合日线缺失，均等待数据。
- 风控：冻结窗口前 ATR14 / 前日收盘（1.2%–8%），初始止损为 ATR×1.2 与配置止损上限取小，
  使用实际 Demo 成交均价生成独立 reduce-only STOP_MARKET。
  标记价浮盈达到 ATR×0.5／×1.2 时，分别锁定 ATR×0.08／×0.6；档位只升不降，
  退出触发与档位写入实际入场意图，重启保留。棘轮由 FA 后台按同步的 Demo 标记价触发
  reduce-only 市价退出，不撤换已有交易所初始止损；进程离线/同步故障时只有交易所初始保护仍生效。
  不固定止盈、不因反向信号自动反手，暂停或关闭总开关仍管理已有 FA 仓位。
- 账户额度、最大损失、杠杆上限、Demo 报价差、外部仓位冲突继续由既有执行层检查。
  绩效按实际成交和交易周期入场策略类型统计；旧 EMA 历史不计入新策略绩效。
  同合约仍只有一个配置实例，已存在仓位必须退出后才能修改策略类型。
- 启用：管理员在 Paper Trade 选择「24/7 永续驱动 (V8)」、合约及自己的额度/方向/风控，
  保存默认暂停，然后确认启用实例与 Demo 新增仓位总开关。没有默认实例/自动启用，不需要额外迁移或环境变量。

## 数据与状态

- `paper_strategy`：策略参数、启停、闭合 K cursor 和状态。
- `paper_intent`：手动操作、信号、执行意图状态与稳定 client ID；策略/闭合时间唯一。
- `paper_exchange_record`：普通/Algo 订单、成交、收入流水，按交易所原生 ID 去重；金额保留原始 Decimal 字符串。
- `paper_account_snapshot`：约每分钟保存权益快照，最近点持续更新；页面显示最近 1440 个点。
- Redis 只存短期连接状态，既有 Streamer leader 负责账户 I/O；每次执行前确认 leader。
- 普通订单及成交推送按真实 ID 去重保存，账户/Algo 变化触发 REST 核对；连接、重连及周期性轮询都核对账户、订单、成交、流水。
  首次同步近期 7 天（共享池、持仓、挂单、策略及收入流水涉及标的），之后重叠窗口增量同步，
  超过交易所保留/分页限制时停止自动执行。App 非共享标的的已成交交易通过账户流水发现，
  挂单通过账户级 openOrders 发现；首次连接前已经取消且未成交的非共享标的订单可能无法发现。
- 账户累计净收益统计已同步 USDT 已实现盈亏、手续费和资金费，不计转账。
  策略统计仅计可归属、无外部干预的已结算往返交易及持仓期间可归属的 USDT 资金费。
  非 USDT 费用或所有权污染不计入策略绩效；最大回撤为已结算累计净收益回撤金额，
  不伪装为盘中逐笔权益回撤。历史不足直接留空。

## 验证与官方契约

默认离线测试使用 MockTransport、隔离测试存储与浏览器路由拦截，不使用真实密钥或发送外部交易请求。
实际 Demo 账户的权限及具体标的/接口支持需配置后由管理员手动核对。
若 Demo 不支持某能力，保留已取得的账户只读信息，执行状态显示暂不可用。

参考（实施时 2026-11-25）：

- [Binance Demo Trading 账户与 API 创建](https://www.binance.com/en-KZ/support/faq/detail/9be58f73e5e14338809e3b705b9687dd)
- [USD-M General Info（Demo endpoint、签名、未知结果）](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info)
- [USD-M REST Trade（普通/Algo 订单）](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade)
- [User Data Streams（连接、账户、成交与 ALGO_UPDATE）](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/user-data-streams)
- [USD-M Change Log](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/change-log)
- [Account REST API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account)
- [Market Data REST（交易规格、TradFi Trading Schedule）](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)
