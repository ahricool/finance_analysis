# 指标说明口径与维护

本次审查以 `d0efd4a710f119197f7a5530cf71a2720a962ef8` 源码为基准。

## 界面覆盖

- Dashboard 的正式趋势市场得分、高脆弱趋势数量、趋势广度
- 自选及证券详情的报价、涨跌、分钟趋势、形态、0DTE 与持仓数字
- ETF 综合排名、因子、状态、动作；保留原有逐项公式，补齐离散标签含义
- Trend 核心分数、Entry、生命周期、脆弱性、箱体、均值回归与事件研究表头
- 共振概览、表格及分来源详情证据；同名字段按来源选择说明
- 盘中确认的状态、固定开盘窗口收益、VWAP、量能近似与追高风险
- 投资组合估值、现金维护、仓位及未实现盈亏
- BTC 策略规则、仓位、绩效和完整交易周期
- 宏观状态、得分、信号覆盖、资产/比值表及贡献拆解
- Quant 排名、模型评价、数据集、市场得分拆解、训练参数与目标组合
- 行业排名、历史、成分股；明确正式收盘和盘中预览差别
- 情绪核心统计、热度、早封率、封单与池表
- 龙虎榜概览、概念分摊、股票原始记录与游资席位样本
- 任务运行状态、时间、耗时和结果口径
- 期权情报复用原有逐项说明，并核对来源、单位与枚举

普通身份字段（名称、代码、日期ID）、操作按钮、导航、段落标题不强行补“重复标签”说明；动态原始JSON保留来源事实，不推测未知字段定义。

## 来源与关键差异

- `trend_following/config.py` 当前日线覆盖率门槛为90%，旧说明95%已改正。
- `trend_following/features.py` 加速度是 `(5日对数斜率−15日对数斜率)×252`；距MA20、均线日变化、有符号效率各有独立单位，不能共用泛化的均线/Path说明。
- `trend_following/{box,mean_reversion,lifecycle,fragility}.py` 提供状态全集、窗口、分量与缺失规则；箱顶距离页面翻转过符号，文案描述页面最终展示值。
- `intraday_confirmation/engine.py` 的5/15/30分钟收益是从开盘起的固定窗口，非滚动收益；量比是日均量按交易时间线性估算，VWAP由闭合5分钟典型价格近似。
- `macro/service.py` 宏观Risk Score越高越偏Risk On。宏观、Trend、Quant三个同名环境的分数尺度与阈值分别说明。
- `interfaces/api/v1/endpoints/holdings.py::summary` 缺失/过期报价持仓不计入总市值，本次只揭示估值不完整风险，不改变估值行为。
- `crypto/performance.py` 只用末尾连续且完整的15分钟仓位快照；CAGR按365自然日年化，胜率只计完整持仓周期。
- `quant/signals/fusion.py` 最终分=60%横截面+40%时间序列−风险扣分，可为负。`qlib_worker/models/targets.py` 预测T+1开盘到T+5收盘的超额收益；`quant/signal_returns.py` 实际回看却是信号日收盘到后续存储K线的绝对价格收益，不能混同。
- `qlib_worker/models/{metrics,training}.py` 模型详情主要标量是有效Walk-forward测试折等权均值；`*Std` 是折间总体标准差。MAE误差与交易研究最大不利变动是不同指标。
- `confluence/{engine,service}.py` 缺失维度不入分母；证据详情保留原始单位，例如预测超额字段数值1表示1个百分点，而行业原始收益差0.01表示1个百分点。
- `dragon_tiger_flow/calculator.py` Top5集中度以正流入概念为单位；概念分摊、股票原始净额与席位样本分别说明。
- `market_sentiment/calculator.py` 早封率以有效时间样本为分母，封单留存取逐股比例中位数；缺失不补零。

## 组件约定

- 保留 `IndicatorHelpLabel` / `BilingualLabel` 与现有Popovers；统一 `MetricHint` 支持鼠标悬停、键盘焦点、点击/轻触固定展开、再次点击及Escape关闭。
- `scope` 必须明确指定领域。不能让 `state`、`marketScore`、`volume` 等在不同模块中自动共用说明；显式 `description` 优先级最高。
- 排序按钮和帮助按钮为同级元素，避免嵌套按钮。帮助点击不能触发排序、行点击或外层详情关闭。
- 长说明使用视口约束、换行和滚动；不新增原生title提示或变更API、计算、过滤、排序、交易/任务操作行为。
- 新增/改名指标时同步补充scope映射与覆盖测试。未知字段不回退成原标签假装已有说明。

## 检查

组件交互测试和领域覆盖测试见 `MetricHint.test.ts`、`metricHints.test.ts`。实际浏览器验证受运行环境限制未执行；组件测试不能替代真实触屏/视口验收。
