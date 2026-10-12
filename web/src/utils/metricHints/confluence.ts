// Sources: confluence/{config,engine,service}.py. Snapshot rules remain the authority for thresholds.
export const confluenceHints: Record<string, string> = {
  strongConfluence: '整日快照中满足强共振规则的股票数，不随当前列表搜索筛选改变。当前规则要求至少4个有效维度、至少3个正向维度、共振分数至少75；页面下方同时展示该快照保存的阈值。强共振是启发式证据归纳，不是上涨概率。',
  ignitionTopIndustry: '整日快照中，达到最低有效维度要求、趋势生命周期为IGNITION（点火），且行业维度为正向的股票数量。行业正向要求行业排名前10且状态不是WEAK或COOLING。',
  topIndustryConfluence: '整日快照中，达到最低有效维度要求，且所在行业强度排名前10的股票数量。该计数只检查排名，不额外要求行业状态为正向。',
  snapshotTradeDate: '这批共振快照的目标交易日期。每个维度采用截至目标日可获取的正式结果，来源日期可能更早；生成时间是本次汇总时间，不代表行情实时更新。',
  confluence: '0–100分：各可用维度贡献之和÷可用权重之和×100。行业/趋势/量化/ETF/龙虎榜权重为25/30/20/15/10。positive（正向）得完整权重，neutral（中性）得一半，negative（负向）得0；unavailable（无数据）不计分也不计入分母。应结合有效维度数阅读，分数不等于胜率。',
  signals: '显示“正向维度数/有效维度数”，最多5个维度：行业、趋势、量化、ETF、龙虎榜。有效包括positive（正向）、neutral（中性）、negative（负向），unavailable（无数据）不算有效。数量越少，证据覆盖越有限。',
  industry: '该股票关联行业的正式行业快照及强度排名，1最强。行业证据是背景，不是个股自身的收益或交易指令；日期以来源卡片为准。',
  lifecycle: '趋势生命周期共有IGNITION（点火）、EMERGING（萌芽）、EXPANSION（扩张）、MATURE（成熟）、EXHAUSTION（衰竭）、BROKEN（破坏）。阶段由趋势与历史状态计算，不表示固定天数后必然进入下一阶段；缺失表示无法判断。',
  lifecycleFragility: '同时展示趋势生命周期和0–100脆弱性分数。阶段为IGNITION（点火）、EMERGING（萌芽）、EXPANSION（扩张）、MATURE（成熟）、EXHAUSTION（衰竭）、BROKEN（破坏）；脆弱性越高表示近期内部恶化证据越多。缺失不等于0或稳定。',
  quantRank: '来源量化快照中该股票的股票池排名，1最好；不是共振列表内重新计算的排名，也不是预测收益百分比。',
  etfRank: '与该股票关联的ETF在其来源轮动快照中的综合排名，1最好；这是行业或风格背景，不是股票自身的排名。',
  '龙虎榜资金': '最近一条可用的1日或原生3日龙虎榜记录净流入，单位人民币元。1日和3日窗口分开理解，不叠加重叠区间；正为净流入，负为净流出，无数据不记作0。',
  whyConfluence: '列出每个来源的状态、实际贡献分、原因和来源交易日。positive（正向）、neutral（中性）、negative（负向）、unavailable（无数据）是全部状态；贡献分上限为该维度权重，而非每个维度都满分100。',
};
