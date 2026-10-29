# 行业到 ETF 轮动池的静态映射

`stocks/industry_etf.py` 保存人工审核的 `US_INDUSTRY_ETF` / `CN_INDUSTRY_ETF` dict，版本为
`industry_etf_v1`。每个条目都有中文注释和可读取的中文理由；无合适代理时明确保存
`IndustryETF(None, reason)`。只使用已有 `us_index_etf` / `cn_index_etf` ETF 轮动池，不新增市场ETF。

这是行业表现代理，不表示ETF真实持仓、指数成分资格或个股业务收入占比。本PR只提交映射注册表、
精确查找函数和覆盖审计工具，供review；尚未启用Confluence ETF评分、改变五维门槛、接口或页面。
ETF有映射也不等于指定日期已经有有效正式指标，后续接入时仍需检查池成员及快照日期。

## 查找与审核规则

- US精确匹配 `(Yahoo sector, Yahoo industry)`，来自 `Instrument.metadata.classification`。
  细分行业有适合的轮动ETF时采用细分代理，否则在该条目上显式选板块代理；例如
  Semiconductors → SMH、区域银行 → KRE、Consumer Electronics → XLK。
  Yahoo与ETF分类不是同一体系，映射是人工经济范围判断，不声称两者成分范围完全一致。
- CN精确匹配 `industry_catalog.industry_code`，源于现有扶摇周同步目录及成员；Instrument本身
  没有CN行业分类。注释保留中文名称，一级行业和细分行业逐项判断。
- 未审核的新行业、错误sector组合、CN自由文本名称及HK全部返回未关联，不做运行时sector回退、
  名称模糊匹配、LLM推断或宽基ETF补齐。
- 美股Shell Companies、REIT—Mortgage、Education & Training Services、Thermal Coal不关联：
  分别因空壳缺经营行业、抵押REIT与权益地产范围不同、教育不宜用必需消费代理、动力煤不宜用油气代理。
- A股钢铁不映射有色金属、整车不一概映射新能源车、自动化不一概映射机器人、制药不一概映射创新药。
  具体机器人、芯片、光伏等子行业有明确映射。无合适代理的行业在dict中逐项保留理由。
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

统计对象只包括 `Instrument.instrument_type = STOCK`，上市状态分开。
有ETF代理表示至少一个映射目标存在于该次生产ETF轮动池（CN 42只、US 49只）中；
不统计ETF本身、指数、不要求该股票属于某个ETF实际持仓，也不代表每日指标已经就绪。

| 当前上市股票范围 | 股票总数 | 有行业分类 | 至少关联一个池内ETF | 占全部股票 | 占已有行业分类股票 |
| --- | ---: | ---: | ---: | ---: | ---: |
| US Instrument分类 | 12,441 | 5,921 | 5,548 | 44.59% | 93.70% |
| CN Instrument + 周同步行业成员 | 5,889 | 5,577 | 3,179 | 53.98% | 57.00% |
| HK Instrument分类 | 2,862 | 0 | 0 | 0.00% | N/A |
| CN + US | 18,330 | 11,498 | 8,727 | 47.61% | 75.90% |
| CN + US + HK | 21,192 | 11,498 | 8,727 | 41.18% | 75.90% |

严格仅使用Instrument内的classification（不读CN行业参考表），覆盖股票只有US的5,548只，
占全部当前上市Instrument股票的26.18%。CN的3,179只必须明确标为来自行业参考表，不能混称为Instrument分类覆盖。

分类条目审核：

| 分类来源 | 实际不同分类数 | 已审核 | 有ETF代理 | 明确未关联 |
| --- | ---: | ---: | ---: | ---: |
| US sector/industry组合 | 145 | 145 | 141（97.24%） | 4 |
| CN行业代码（含一级和细分） | 320 | 320 | 183（57.19%） | 137 |

- US：6,520只当前上市股票缺分类；已分类但明确不关联373只，不能通过扩大sector回退掩盖。
- CN：312只缺行业成员；已分类但无适合代理2,398只；69只覆盖股票存在多个不同代理候选，
  仍只计一次，不把多层行业关系当多只股票。
- 另外US退市213只、HK退市130只，均无分类及映射；含退市总分母为21,535只，
  覆盖仍为8,727只（40.52%）。
- 当前样本没有尚未审核的来源行业；未来新增类别会出现在审计输出的 `unreviewed`。

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
