# A股 ETF 动量轮动

## 功能与边界

ETF Rotation 是独立、规则驱动且可解释的 A 股/美股 ETF 快速轮动模块。它在收盘后计算完整横截面排名、Entry Score、状态与候选，并保存 point-in-time snapshot。

生产信号代表 T 日收盘后才可获得的信息。回测和后续执行必须默认使用 **T+1 Open** 或更晚价格，不能假设以 T 日 Close 成交。

## 数据来源与日线同步

证券与成员读取 PostgreSQL；有限的 ETF 和 benchmark 日线通过 MarketDataService 的 `db_fresh` 读取，不直接调用具体 Provider。
DB 的最新日线达到请求结束日期时直接返回本地区间；落后时读取 DB 历史并批量补最近约 10 个自然日的重叠尾部，按交易日合并，Remote 覆盖同日 DB。
完全没有历史时远程获取本次请求窗口。远程结果仅用于本次计算，不写 `stock_daily`；不检查历史中间缺口、停牌或上市前日期。价格始终使用前复权语义，不重复复权。

ETF Rotation 通过 `get_etf_universe()` / `UniverseRepository` 读取 `cn_index_etf` / `us_index_etf`。
这两个单市场 STRATEGY Universe 是唯一的 curated ETF 成员池，分别被 `cn_daily_sync` / `us_daily_sync` include，日线任务会主动维护其 `stock_daily`。
每周 `reference_data_sync` 不会自动替换 curated ETF membership。池外 benchmark 不会扩大 Daily Sync 范围。

## 固定 Universe

成员保存在 `universe_member`，分类、主题与风险组位于 member metadata。以下为初始参考清单：

| Code | Name | Category | Theme | Risk Group |
| --- | --- | --- | --- | --- |
| 588000.SH | 科创50ETF | BROAD_INDEX | STAR50 | BROAD_GROWTH |
| 159915.SZ | 创业板ETF | BROAD_INDEX | CHINEXT | BROAD_GROWTH |
| 512800.SH | 银行ETF | FINANCE | BANK | FINANCE |
| 512880.SH | 证券ETF | FINANCE | BROKER | FINANCE |
| 159851.SZ | 金融科技ETF | FINANCE | FINTECH | FINANCE |
| 512200.SH | 房地产ETF | REAL_ESTATE_INFRA | REAL_ESTATE | REAL_ESTATE_INFRA |
| 516970.SH | 基建ETF | REAL_ESTATE_INFRA | INFRASTRUCTURE | REAL_ESTATE_INFRA |
| 159928.SZ | 消费ETF | CONSUMER | CONSUMER | CONSUMER |
| 512690.SH | 酒ETF | CONSUMER | LIQUOR | CONSUMER |
| 159996.SZ | 家电ETF | CONSUMER | HOME_APPLIANCE | CONSUMER |
| 512170.SH | 医疗ETF | HEALTHCARE | MEDICAL | HEALTHCARE |
| 159992.SZ | 创新药ETF | HEALTHCARE | INNOVATIVE_DRUG | HEALTHCARE |
| 512400.SH | 有色金属ETF | RESOURCE | NONFERROUS | RESOURCE |
| 517520.SH | 黄金股ETF | RESOURCE | GOLD_MINERS | RESOURCE |
| 516150.SH | 稀土ETF | RESOURCE | RARE_EARTH | RESOURCE |
| 515220.SH | 煤炭ETF | RESOURCE | COAL | RESOURCE |
| 516020.SH | 化工ETF | RESOURCE | CHEMICAL | RESOURCE |
| 159611.SZ | 电力ETF | UTILITY | POWER | UTILITY |
| 159825.SZ | 农业ETF | AGRICULTURE | AGRICULTURE | AGRICULTURE |
| 512480.SH | 半导体ETF | TECHNOLOGY | SEMICONDUCTOR | TECH_HARDWARE |
| 159995.SZ | 芯片ETF | TECHNOLOGY | CHIP | TECH_HARDWARE |
| 515880.SH | 通信ETF | TECHNOLOGY | COMMUNICATION | TECH_HARDWARE |
| 159732.SZ | 消费电子ETF | TECHNOLOGY | CONSUMER_ELECTRONICS | TECH_HARDWARE |
| 159819.SZ | 人工智能ETF | TECHNOLOGY | AI | TECH_SOFTWARE |
| 516510.SH | 云计算ETF | TECHNOLOGY | CLOUD_COMPUTING | TECH_SOFTWARE |
| 159852.SZ | 软件ETF | TECHNOLOGY | SOFTWARE | TECH_SOFTWARE |
| 159869.SZ | 游戏ETF | TMT | GAME | TECH_SOFTWARE |
| 512980.SH | 传媒ETF | TMT | MEDIA | TECH_SOFTWARE |
| 562500.SH | 机器人ETF | ADVANCED_MANUFACTURING | ROBOT | ADVANCED_MANUFACTURING |
| 515970.SH | 工程机械ETF | ADVANCED_MANUFACTURING | CONSTRUCTION_MACHINERY | ADVANCED_MANUFACTURING |
| 515030.SH | 新能源车ETF | AUTO | NEW_ENERGY_VEHICLE | NEW_ENERGY_AUTO |
| 516520.SH | 智能驾驶ETF | AUTO | AUTONOMOUS_DRIVING | NEW_ENERGY_AUTO |
| 159565.SZ | 汽车零部件ETF | AUTO | AUTO_PARTS | NEW_ENERGY_AUTO |
| 159566.SZ | 储能电池ETF | NEW_ENERGY | ENERGY_STORAGE | NEW_ENERGY |
| 515790.SH | 光伏ETF | NEW_ENERGY | PHOTOVOLTAIC | NEW_ENERGY |
| 159326.SZ | 电网设备ETF | NEW_ENERGY | POWER_GRID | NEW_ENERGY |
| 512660.SH | 军工ETF | DEFENSE_SPACE | DEFENSE | DEFENSE_SPACE |
| 563230.SH | 卫星ETF | DEFENSE_SPACE | SATELLITE | DEFENSE_SPACE |
| 563380.SH | 航空航天ETF | DEFENSE_SPACE | AEROSPACE | DEFENSE_SPACE |
| 563320.SH | 通用航空ETF | DEFENSE_SPACE | LOW_ALTITUDE_ECONOMY | DEFENSE_SPACE |

新增或删除 ETF 时更新 `cn_index_etf` / `us_index_etf` 的数据库成员；ETF Rotation 和对应 Daily Sync 都读取同一池，不维护第二套 ETF list。

## Features

所有计算函数位于独立 `etf_rotation` 域，不依赖 Quant Feature Engine：

- `ret_Nd = close[t] / close[t-N] - 1`，N 为 1/3/5/10/20。
- `momentum_acceleration_3d = ret_3d - previous_3d_return`。
- `previous_5d_return = close[t-5] / close[t-10] - 1`。
- `momentum_acceleration_5d = ret_5d - previous_5d_return`。
- `ma10_ratio` 用于绝对趋势门槛；`ma20_ratio` 只用于追高风险。
- 对 log(close) 计算 5/10/15 日近期加权回归；`trend_quality_15d = annualized_slope_15d * trend_r2_15d`。
- `signed_efficiency_ratio_10d` 保留净移动方向，范围约为 -1 到 1。
- `volume_ratio_5d` 为最近 5 根平均 volume / 最近 20 根平均 volume。
- `avg_amount_20d` 为最近 20 根非空 amount 的平均值。
- `realized_vol_20d` 为最近 20 个 close-to-close return 的样本标准差乘 `sqrt(252)`。
- `distance_from_20d_high = close[t] / max(close[t-19:t]) - 1`。

完整计算至少需要 21 根截至 T 日的日线。横截面 rank 中 1 为最强；percentile 中 100 为最强、0 为最弱。

`rank_change_Nd = N 个历史 snapshot 交易日之前的 Composite rank - 当前 Composite rank`，N 为 1/3/5；正值表示改善。

## Momentum 与 Entry Score

Momentum Score 使用横截面 percentile，不直接加权收益：

```text
0.30 * pct_rank_3d
+ 0.35 * pct_rank_5d
+ 0.25 * pct_rank_10d
+ 0.10 * pct_rank_20d
```

Composite 为 Momentum 30% + RS5/10/20 25% + Acceleration 25% + Trend Quality15 15% + Signed ER10 5%。Entry Score 以 Composite 为基础，保留温和单日上涨、放量确认、MA20 偏离和单日暴涨惩罚。

所有权重、阈值、coverage 和候选限制集中在 `etf_rotation/config.py`。

## State 与 Candidates

状态 priority 固定为：`EXHAUSTED > COOLING > EMERGING > STRONG > TRENDING > WEAK > NEUTRAL`。EMERGING 使用 3 日排名改善、Acceleration、RS10 与 10 日正斜率识别刚启动热点。

BUY 要求 Composite Top4、Entry Score 至少 70 且状态为 EMERGING/STRONG/TRENDING。HOLD 要求 Top6、Composite 至少 60，并满足加速度或 5 日收益条件；明显加速度恶化或单日排名坠落直接 EXIT。候选相关性只使用最近 20 个交易日。

## Data readiness 与持久化

默认运行日期是最新已完成的 CN trading session。任务要求每只 enabled ETF 在该日有 bar，默认 daily coverage 至少 95%；覆盖达到阈值但不完整时继续并返回 warning。历史重跑检查目标日 bar 是否存在，而不是要求目标日仍为数据库最新日。

有 T 日 bar 仍不代表可排名；完整 feature 可计算数量 / enabled universe 数量也必须至少 95%。任一 coverage 不足时抛出清晰错误，且不写入新 snapshot。

`etf_momentum_snapshot` 每日保存所有 rankable ETF，唯一约束为 `(trade_date, symbol_id)`。同日重跑通过 PostgreSQL upsert 更新，并在同一事务删除不再 rankable 的同日陈旧行。主要索引覆盖 `(trade_date, entry_score)`、`(symbol_id, trade_date)` 和 `(trade_date, is_candidate, candidate_rank)`。Ranking、Candidates、Detail、History 全部直接查询此 PostgreSQL 表，不读写 Redis。

## Scheduler、手动运行与 API

Celery Beat 任务 `scheduled.etf_rotation_cn` / `scheduled.etf_rotation_us` 默认分别在工作日
18:30 Asia/Shanghai / 18:30 America/New_York 进入 `analysis` queue。时间顺序不是数据正确性的保障，
任务自身总会执行 readiness 检查。

管理员可在前端点击“手动运行”，或调用：

```http
POST /api/v1/etf-rotation/run
Content-Type: application/json

{"trade_date": null}
```

它只异步提交 Celery，不在 FastAPI request thread 计算。查询接口均需登录：

- `GET /api/v1/etf-rotation/ranking?market=&trade_date=&sort_by=&limit=`
- `GET /api/v1/etf-rotation/candidates?market=&trade_date=&limit=`
- `GET /api/v1/etf-rotation/dates?market=`
- `GET /api/v1/etf-rotation/universe?market=`
- `GET /api/v1/etf-rotation/{code}?market=&limit=60`
- `POST /api/v1/etf-rotation/run`（admin）

`candidates` 返回受 `limit` 限制的 BUY/HOLD `candidates`，以及不受该限制的当日 `exits`；兼容字段
`items` 继续映射到当前 candidates。`dates` 按市场返回已持久化 snapshot 的交易日，降序排列；
`ranking` / `candidates` 不传 `trade_date` 时回落到该市场最新交易日。前端入口为“研究 → ETF动量轮动”，
可用 A股/美股切换和日期选择器查看某一市场某一日的排名与候选。
