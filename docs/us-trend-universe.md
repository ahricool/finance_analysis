# 美股趋势股票池

美股趋势继续通过 `trend_following/universe.py::get_universe("US")` 读取
`us_trend`。数据库 `UniverseInclude` 定义：

- `us_trend` → `us_sp500`、`us_sp400`、`us_nasdaq100`。
- `us_daily_sync` → `us_sp500`、`us_sp400`、`us_nasdaq100`、`us_index_etf`、`us_macro`。
- `us_market_structure` → `us_sp500`。

`UniverseResolver` 在每层按 canonical `Instrument.code` 合并并排序。同一代码只返回
一次；不同 share class 仍是不同证券。`UniverseMember` 的唯一键是
`(universe_id, instrument_id)`，因此一个证券的多个指数归属不会因趋势去重而丢失。
正式计算、快照排名和 preview 共用现有入口；趋势算法、阈值、排名规则不变。
前端没有指数筛选结构，本次保持原有状态/名称筛选，默认展示全部可计算成员。

## 来源与同步

继续使用现有 `USIndexConstituentProvider`，由每周 Reference Data Sync 同步：

| Universe | Provider index code | Wikipedia 当前成分表 |
| --- | --- | --- |
| `us_sp500` | `SP500` | https://en.wikipedia.org/wiki/List_of_S%26P_500_companies |
| `us_sp400` | `SP400` | https://en.wikipedia.org/wiki/List_of_S%26P_400_companies |
| `us_nasdaq100` | `NASDAQ100` | https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies |

每个指数单独抓取、确认 Instrument Master 中的证券，再在独立事务内替换关系：
新增成员、更新来源/metadata、删除该指数已剔除的关系。单个响应内重复代码先合并。
请求失败、空结果、证券元数据缺失或数据库写入失败时，保留该指数旧关系，任务返回
`partial` 并记录 `failed_universes`；另外两个指数继续处理。不会删除其他指数的关系。
这些是当前成员，不是历史时点成员；历史重算仍具有现有的存活偏差。

## 部署与数据准备

`0057_us_trend_universe` 是数据迁移，新增 `us_sp400`、CN/US Market Structure 策略池和包含关系，不改表结构；
启动 seed 同步更新，支持空库。迁移不访问公网，也不伪造初始 SP400 成分。
迁移后先运行 Reference Data Sync，再运行 US Daily Sync 补齐新增股票历史，最后运行
US Trend/preview。日线不足仍按现有覆盖率/历史长度规则处理。
旧正式快照和 Redis preview 不会自动重算；后续任务运行后才体现扩容。

日线同步按已有历史窗口分组，新增证券走现有完整历史补齐逻辑。Yahoo 仍按默认
100 只一批、最多 3 workers 获取数据；Universe 查询次数随指数数变化，不随证券数
变化，成员关联的 Instrument 使用 joined loading。趋势历史、前态及健康历史均为
批量查询；preview 有两次池解析（报价和计算阶段），没有逐股票重读 Universe。

Market Structure 使用独立 `us_market_structure` / `cn_market_structure`，US 只含
SP500，CN 只含 CSI300/500/1000，均不跟随 Daily Sync 或 Trend 扩容。
Quant 的独立 Universe 定义保持原样。

CN Daily Sync 直接包含 CSI300/500/1000/2000 和 `cn_index_etf`；CN Trend 仍为
四个指数并集。复用现有 `cn_csi2000`，由 AkShare `932000` 同步当前成分。
CSI2000 不再使用专属 remote-tail 分支：正式趋势和 preview 历史统一批量读
`stock_daily`，只有 benchmark 保留 `db_fresh`。无历史股票通过现有日线任务
`has_daily_data=false` 分支补 initial history，部署时也应运行 CN Daily Sync。
Universe 解析无逐股票查询；日线任务原有逐证券 `has_daily_data` 检查保持不变，
本次未进行无关性能重构。

## 来源实测（2026-09-18 14:59 UTC）

通过上述 Provider 实际抓取并按 canonical code 计算：

| 集合 | 不重复证券代码数 |
| --- | ---: |
| SP500 | 503 |
| SP400 | 400 |
| NASDAQ100 | 102 |
| 三者并集 | 918 |
| NASDAQ100 − SP500 | 15 |

SP500 与 SP400 无重叠。Nasdaq-100 中不属于 SP500 的实际例子：
`ARM.US`、`ASML.US`、`MELI.US`、`PDD.US`、`SHOP.US`。
数量是抓取时 Wikipedia 表格的观察值，不保证名义指数数量恰为 500/400/100，
也不代表已经部署或写入生产库；页面可能包含不同生效时点的调整，后续同步以届时
源页面为准。实际成功计算数量还取决于日线覆盖率。
