# 双引擎日线回测

V1 提供单标的、日 K、只做多的 `sma_cross` 策略。信号使用交易日收盘后的完整数据计算，并在下一交易日开盘成交。回测只读取 PostgreSQL 中的 `market_data_symbol` 和 `stock_daily`，执行期间不会下载 RQAlpha bundle，也不会向行情服务补数。

## 运行时兼容性

- Python：`>=3.13,<3.14`
- Backtrader：官方包 `backtrader==1.9.78.123`
- RQAlpha：`rqalpha==6.2.0`
- Pandas：RQAlpha 6.2.0 要求 `<3.0.0`，因此项目锁定 `pandas>=2.2.0,<3.0.0`；Python 和 NumPy 版本没有降低。

Backtrader 当前声明 US、CN；RQAlpha 当前只声明 CN。RQAlpha 6.2.0 的开源核心没有 US 市场枚举，因此不能用中国市场 bundle 冒充美股。HK 因 `lot_size` 历史数据尚未完整而未在任何引擎能力中启用。

## 数据和市场限制

`stock_daily` 保存原始未复权价格。`backtest_run.price_mode` 固定记录为 `raw`，结果和页面会提示拆股、分红和除权风险。A 股回测要求日线包含 `limit_up`、`limit_down` 和 `suspended`；缺失时 preflight 会阻止任务创建。A 股使用 100 股整数手、T+1、涨跌停限制和项目统一费用模型。港股不会在缺少逐标的 lot size 时默认使用 100 股。

## 引擎适配

Backtrader 使用 `PostgreSQL -> pandas.DataFrame -> PostgreSQLPandasData`，策略类继承 `bt.Strategy`，使用原生 SMA、`next`、`next_open` 和 broker。

RQAlpha 使用 `PostgreSQLRQAlphaDataSource` 提供证券、交易日历、日线和开盘集合竞价数据，通过项目内 mod 注入 `Environment`。策略使用原生 `init`、`before_trading`、`open_auction`、`handle_bar`、`after_trading` 和 `order_shares`；费用由同一项目 FeeModel 注入 RQAlpha transaction-cost decider。

两套引擎完成后都转换为 `BacktestResult`，最终收益、回撤、Sharpe、波动率和交易统计由 `BacktestMetricsCalculator` 统一计算。
