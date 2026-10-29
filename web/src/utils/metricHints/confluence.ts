// Sources: confluence/{v2,service}.py. Snapshot rules remain the authority for thresholds.
export const confluenceHints: Record<string, string> = {
  strongConfluence: 'V2主要指标至少2个可用且至少2个正向，综合分≥75；每个市场每日最多10条。V1历史仍按保存的旧规则阅读。不是上涨概率。',
  ignitionTopIndustry: '所选正式快照中行业正向且20日趋势为IGNITION的数量。',
  topIndustryConfluence: '所选正式快照中行业排名前10的数量。',
  snapshotTradeDate: '目标交易日。V2股票指标只取同日正式结果；宏观按中美时点取已完成美股日，龙虎榜使用最近3个CN交易日。',
  confluence: 'V2.2精选门槛60分，每市场每天最多10个；研究排行最多50条，观察项不属于正式信号。V2主要权重：宏观15、行业ETF20、行业强度15、趋势30；辅助：Quant7、期权5、情绪4、龙虎榜4。缺失留空，不计分母，其他权重按比例归一。各核心支持度为0–100。V1历史保持原始规则。',
  signals: '正向/有效维度，V2最多8个家族。趋势20/40/60及三种替代路线属于同一家族，不作为9个独立信号重复计数。',
  macro: 'V2.1宏观15%采用行业宏观适配度，整体风险偏好仅作背景。行业敏感系数为研究规则，不是统计回归或收益概率。分类缺失、未审核或因子覆盖不足65%则留空并分摊；历史V2保留统一风险偏好分。',
  industry: '该股票关联行业的正式行业快照及强度排名，1最强。行业证据是背景，不是个股自身的收益或交易指令；日期以来源卡片为准。',
  lifecycle: '趋势生命周期共有IGNITION（点火）、EMERGING（萌芽）、EXPANSION（扩张）、MATURE（成熟）、EXHAUSTION（衰竭）、BROKEN（破坏）。阶段由趋势与历史状态计算，不表示固定天数后必然进入下一阶段；缺失表示无法判断。',
  lifecycleFragility: '同时展示趋势生命周期和0–100脆弱性分数。阶段为IGNITION（点火）、EMERGING（萌芽）、EXPANSION（扩张）、MATURE（成熟）、EXHAUSTION（衰竭）、BROKEN（破坏）；脆弱性越高表示近期内部恶化证据越多。缺失不等于0或稳定。',
  quantRank: '来源量化快照中该股票的股票池排名，1最好；不是共振列表内重新计算的排名，也不是预测收益百分比。',
  etfRank: '与该股票关联的ETF在其来源轮动快照中的综合排名，1最好；这是行业或风格背景，不是股票自身的排名。',
  '龙虎榜资金': '最近一条可用的1日或原生3日龙虎榜记录净流入，单位人民币元。1日和3日窗口分开理解，不叠加重叠区间；正为净流入，负为净流出，无数据不记作0。',
  whyConfluence: '列出每个来源的状态、实际贡献分、原因和来源交易日。positive（正向）、neutral（中性）、negative（负向）、unavailable（无数据）是全部状态；贡献分上限为该维度权重，而非每个维度都满分100。',
};
