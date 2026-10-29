# 行业到 ETF 轮动池的静态映射

`stocks/industry_etf.py` 保存人工审核的 `US_INDUSTRY_ETF` / `CN_INDUSTRY_ETF` dict，版本为
`industry_etf_v2`。每个条目都有中文注释和可读取的中文理由；无合适代理时明确保存
`IndustryETF(None, reason)`。只使用已有 `us_index_etf` / `cn_index_etf` ETF 轮动池，不新增市场ETF。

这是行业表现代理，不表示ETF真实持仓、指数成分资格或个股业务收入占比。个股详情弹窗在行业下方
展示关联ETF的名称和代码，可展开查看中文关联理由。分类API返回`etf_proxies`及
`etf_proxy_unavailable_reasons`；Confluence已使用行业ETF正式指标，评分规则见`docs/confluence.md`。
ETF有映射不等于指定日期已有有效正式指标，仍需检查池成员及快照日期。

## 查找与审核规则

- US精确匹配 `(Yahoo sector, Yahoo industry)`，来自 `Instrument.metadata.classification`。
  细分行业有适合的轮动ETF时采用细分代理，否则在该条目上显式选板块代理；例如
  Semiconductors → SMH、区域银行 → KRE、Consumer Electronics → XLK。
  Yahoo与ETF分类不是同一体系，映射是人工经济范围判断，不声称两者成分范围完全一致。
- CN精确匹配 `industry_catalog.industry_code`，源于现有扶摇周同步目录及成员；Instrument本身
  没有CN行业分类。注释保留中文名称，一级行业和细分行业逐项判断。
- 未审核的新行业、错误sector组合、CN自由文本名称及HK全部返回未关联，不做运行时sector回退、
  名称模糊匹配、LLM推断或宽基ETF补齐。
- 优先同业或板块代理，无同业时允许相邻产业链、共享需求或资本开支周期的近似ETF；新增近似关联
  在注释与reason中以“近似替代”说明依据和差异。例如钢铁→有色金属观察金属周期、风电→光伏
  观察新能源设备投资、汽车整车→新能源车观察产销周期，均不声称是相同子行业。
- US教育培训→XLY可选消费、动力煤→XLE能源、抵押REIT→XLF金融作为近似替代；
  不机械沿用Yahoo的sector。仅Shell Companies缺稳定经营行业、CN“综合”缺明确主业，继续留空。
- 每个行业固定一个代理，不随当日ETF排名挑选赢家。一个CN股票可同时属于多个层级行业；
  不同层级可能给出不同代理，覆盖统计按股票去重，另报告多代理股票数，不擅自选分数最高者。
- 分类表是当前观测，不是历史行业归属。当前映射及分类不得直接套用至过去的历史共振。

使用示例：

```python
from finance_analysis.stocks.industry_etf import resolve_industry_etf

resolve_industry_etf("US", "Semiconductors", sector="Technology")
resolve_industry_etf("CN", "881155.TI")  # 银行 → 512800.SH
```

## 生产只读快照覆盖率（2026-10-29）

统计对象只包括数据库标记 `Instrument.instrument_type = STOCK` 的记录，上市状态分开。
**这不是已清洗的普通公司股票分母**：后续抽样发现AAA、AAAU、AAPU等实际ETF被标记为STOCK；
本表保留同一快照口径供前后比较，不能将所有缺分类记录称为公司股票。证券类型清洗后需另行重算。
有ETF代理表示至少一个映射目标存在于该次生产ETF轮动池（CN 42只、US 49只）中；
排除数据库已标记ETF或INDEX的记录；不要求实际持仓，也不代表每日指标已经就绪。

| 当前ACTIVE记录范围 | STOCK记录数 | 有行业分类 | 至少关联一个池内ETF | 占全部STOCK记录 | 占已有行业分类记录 |
| --- | ---: | ---: | ---: | ---: | ---: |
| US Instrument分类 | 12,441 | 5,921 | 5,634 | 45.29% | 95.15% |
| CN Instrument + 周同步行业成员 | 5,889 | 5,577 | 5,559 | 94.40% | 99.68% |
| HK Instrument分类 | 2,862 | 0 | 0 | 0.00% | N/A |
| CN + US | 18,330 | 11,498 | 11,193 | 61.06% | 97.35% |
| CN + US + HK | 21,192 | 11,498 | 11,193 | 52.82% | 97.35% |

严格仅使用Instrument内的classification（不读CN行业参考表），覆盖只有US的5,634条，
占全部当前ACTIVE STOCK记录的26.59%。CN的5,559条必须明确标为来自行业参考表。

分类条目审核：

| 分类来源 | 实际不同分类数 | 已审核 | 有ETF代理 | 明确未关联 |
| --- | ---: | ---: | ---: | ---: |
| US sector/industry组合 | 145 | 145 | 144（99.31%） | 1 |
| CN行业代码（含一级和细分） | 320 | 320 | 319（99.69%） | 1 |

- US：6,520条缺分类；已分类但未关联287条，均为Shell Companies。
- CN：312条缺行业成员；已分类未关联18条，均为“综合”；151条覆盖记录有多个不同代理候选，
  仍只计一次。多代理在详情中全部展示，重复ETF合并并保留每个行业的理由。
- 另外US退市213条、HK退市130条，均无分类及映射；含退市分母21,535条，覆盖11,193条（51.98%）。
- 相比v1同快照：CN覆盖3,179→5,559，US覆盖5,548→5,634；合计8,727→11,193。
- 已知465个分类组合中463个有ETF代理；当前样本没有尚未审核的来源行业。
- 补查当前生产`us_sp500`：503个证券代码全部具有sector/industry（100%）；这与大目录STOCK记录的覆盖率是不同范围。
- 近似关联只代表共享环境，不能将高覆盖率解释为高准确率，不能把多个关联ETF当独立信号重复计分。

## 详情显示与读取边界

`GET /api/v1/stocks/{code}/classification`保留已有行业与指数，额外返回关联ETF及未关联原因。
领域服务先按dict解析候选，再用一条批量SQL查当前启用的轮动Universe成员与Instrument名称，
只接受同市场、ACTIVE且属于启用轮动池的成员；移除或停用的ETF不显示，返回明确不可用原因。
ETF资格以配置的轮动池为准，不将Instrument.instrument_type作为关联门槛；上游目录的粗类型不能切断绑定。
ETF自身不进行股票行业映射。不调用Provider、不计算排名、不访问Preview或行情，也不写库。

详情复用已有分类请求及取消/缓存机制，切股和关闭时同时清除行业及ETF旧结果。
关联名称/代码为换行标签，中文依据默认折叠；无分类或明确未关联时展示空态与原因。

## 重算方法

离线工具不连接数据库、不初始化应用或触发迁移。先由只读连接导出两份临时JSON：

- Instrument文件：`{"stocks": [{"market", "code", "listing_status", "metadata"}],
  "etfs": [{"code"}]}`。stocks只含STOCK，etfs来自两个实际轮动Universe当前成员；
  `metadata.classification`保留原始sector/industry。etfs字段缺省时仅检查静态映射，不能声称池内覆盖。
- CN参考文件：`[{"industry_code", "industry_name", "stock_code"}]`，来自
  `industry_catalog LEFT JOIN industry_membership USING (industry_code)`；统计会再与Instrument证券精确匹配。

```bash
PYTHONPATH=src uv run python scripts/report_industry_etf_coverage.py \
  /tmp/instruments.json --cn-reference /tmp/cn-industry-reference.json
```

输出按market/listing_status分组，分别报告total、classified、covered、multiple_proxies及两种分母的比例。
重复Instrument身份会报错；同一股票重复行业成员会去重；映射ETF不在输入实际池时不计覆盖。
不将原始全量股票导出文件或凭据提交仓库。

维护映射时，新增或移除ETF须核对 `database/index_etf.py` 与生产实际池，更新版本、中文理由及本审计。
本PR验证包含池内目标约束、误关联边界、未知行业处理、覆盖去重及缺分类/退市分母测试。

## ETF身份与关联资格的边界（2026-10-30排查）

LMT的Yahoo行业为Industrials / Aerospace & Defense，既有映射目标为XAR.US，XAR在启用的美股轮动池内，
并有10/26–10/28正式ETF指标。此前未显示绑定的原因是关联查询额外要求Instrument类型为ETF。
生产美股轮动池49个成员中43个被上游目录标为STOCK，因此被重复校验过滤。

更新责任链：Celery Beat每周日上海08:00的`reference_data_sync`（ingestion队列）→
`ReferenceDataSyncService`→`InstrumentSyncService.sync_instruments_detailed`→TickFlow主目录→
`InstrumentRepository.upsert_symbols`。10/25 08:00任务及Instrument.updated_at一致，XAR/XLK/IGV/XLC
原始metadata.provider_type均为stock。独立的Yahoo行业同步只更新classification，不负责证券类型。
部分核心/宏观ETF在既有种子维护中被恢复为ETF，因而表面上只有某些关联缺失。

关联资格现在由人工行业映射和实际启用的轮动池共同决定；详情查询仍限制同市场、ACTIVE，
共振还要求同日正式ETF快照及核心分数。没有放开到任意市场ETF，不调用LLM或实时Provider。
Instrument的证券类型仍由原主数据流程维护，本改动不手工改写类型或新增yfinance写回逻辑。
因此即使后续目录再次返回STOCK，绑定及ETF证据读取也不会退化；池移除/停用、退市或缺正式数据仍不可用。

一次性只读Yahoo抽查：XAR、XLK、IGV、XLC、XLU的quoteType均为ETF，LMT为EQUITY。
这仅确认排查样本，不成为在线关联依赖，也不声称已核验全市场类型。

读取生产正式源，在本地复算9个已存日期（未写生产）：
- 10/26–10/28美股有效ETF证据742→5634；标普500与纳指100并集518只中，覆盖96→517；剩余VYLR为Shell Companies，按既有规则保持未关联。
- 新PR原样repository代码在READ ONLY事务中再次验证：LMT→XAR和五个受影响代理的详情名称均恢复。
- A股同周所有精选名单与分数一致。美股10/23仍0；10/26由4→10、10/27由4→1、10/28由1→4。
  缺失证据恢复后有加分也有扣分，数量增加不代表收益改善，不为了纳入科技权重股改评分门槛。
- 原周入选并非全是小盘：CRL/WAT/WST/MTD属于当前SP500池；NWE属于SP400池。
  权重股未入选还涉及实际Trend20/40/60和ETF强度，修复关联不等于保证其入选。

回归测试模拟XAR类型连续STOCK→ETF→STOCK→STOCK更新，验证详情绑定和共振指标持续可用；
并覆盖停用轮动池、退市、移出池、未来快照不可用。类型校验移除只发生在目标ETF关联读取，
股票候选范围和其他模块类型策略保持原有逻辑。部署后需显式重算历史共振，GET不会重算保存的旧结果。

验证：完整后端门禁3255 passed、51 skipped、2 deselected、92 subtests；原样PR repository在生产只读事务中验证。
两轮自查分别核对池作为资格来源与类型反复变化、市场/在市/启用/成员/正式日期边界。前端源码未改。
