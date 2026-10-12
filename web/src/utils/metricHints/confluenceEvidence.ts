import { trendIndicatorDescriptions as trend } from '@/components/trend-following/indicatorDescriptions';
import { indicatorDescriptions as etf } from '@/components/etf-rotation/indicatorDescriptions';
import { quantHints } from './quant';
import { industryHints } from './industry';
import { confluenceHints } from './confluence';

/** Explicit source-field mappings for the evidence detail grid (values remain untouched). */
export const confluenceEvidenceHints: Record<string, Record<string, string>> = {
  'confluence-trend': {
    trendLifecycle: trend.lifecycle!, state: trend.state!, trendScore: trend.trend!, rank: trend.rank!,
    previousRank: '此股票上一次可用正式趋势快照的Alpha排名，日期由“前次日期”显示；可能不是紧邻的上一交易日。',
    trendDurationDays: trend.trendDuration!, fragilityScore: trend.fragility!, trendAcceleration: trend.trendAcceleration!,
    trendQuality: '趋势健康分析的原始拟合质量=15日加权R²×100，范围0–100。这里没有乘上涨方向系数，不等同于Alpha评分中的R²Quality。',
    rsScore: trend.relativeStrength!,
  },
  'confluence-quant': {
    universeRank: quantHints['排名']!, finalScore: quantHints['最终得分']!, signal: quantHints['信号']!,
    predictedReturn: '横截面模型预测T+1开盘至T+5收盘相对市场基准的超额收益，证据格显示的原始数值单位为百分点：1表示预计跑赢基准1个百分点。此处没有百分号，也不能把1再乘100。模型预测不保证实现。',
    crossSectionScore: quantHints['横截面']!,
  },
  'confluence-etf': {
    rank: etf.rank!, state: etf.state!, compositeScore: etf.composite!, entryScore: etf.entry!,
    rankChange1D: etf.rankChange!, rankChange3D: etf.rankChange!, rankChange5D: etf.rankChange!,
  },
  'confluence-industry': {
    strengthRank: industryHints['强度排名']!, strengthScore: industryHints['综合强度']!, state: industryHints['状态']!,
    rankChange1D: industryHints['1 日排名变化']!, rankChange3D: industryHints['3 日排名变化']!, rankChange5D: industryHints['5 日排名变化']!,
    momentumAcceleration5D: '近期5日行业收益−再往前5日行业收益，证据格展示原始小数比例，例如0.02为增强2个百分点；它不是资金流入。',
  },
  'confluence-dragonTiger': {
    rangeDays: '1为单日龙虎榜，3为来源原生3日榜。不同窗口分别读取，不把多个重叠3日榜累加。',
    netInflow: confluenceHints['龙虎榜资金']!,
    institutionNetInflow: '该条龙虎榜记录中机构口径的净流入，单位人民币元。机构与游资分类可能重叠，不能相加推算全市场流入。',
    hotMoneyNetInflow: '该条龙虎榜记录中已识别游资口径净流入，单位人民币元；缺失不等于0。它不是所有非机构资金。',
  },
};
