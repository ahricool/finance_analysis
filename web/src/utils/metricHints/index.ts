import { taskHints } from './tasks';
import { confluenceEvidenceHints } from './confluenceEvidence';
import { studyHints } from './study';
import { industryHints } from './industry';
import { trendIndicatorDescriptions as trend } from '@/components/trend-following/indicatorDescriptions';
import { watchHints } from './watch';
import { flowHints } from './flow';
import { sentimentHints } from './sentiment';
import { quantHints, quantDatasetHints } from './quant';
import { holdingsHints } from './holdings';
import { signalHints } from './signal';
import { intradayHints } from './intraday';
import { macroHints } from './macro';
import { cryptoHints } from './crypto';
import { confluenceHints } from './confluence';

export const metricHints: Record<string, Record<string, string>> = {
  ...confluenceEvidenceHints,
  intraday: intradayHints,
  macro: macroHints,
  macroSignal: { ...macroHints, 信号: '参与宏观评分的资产或资产比值名称；每项有自己明确的Risk On方向，例如VIX下降才得满额贡献，不能把这列名称解释为全部看涨或看跌。' },
  holdings: holdingsHints,
  signal: signalHints,
  quant: quantHints,
  quantDataset: quantDatasetHints,
  quantModel: { ...quantHints, 状态: quantHints['模型状态']! },
  industry: industryHints,
  study: studyHints,
  tasks: taskHints,
  watch: watchHints,
  flow: flowHints,
  sentiment: sentimentHints,
  trend: {
    ...trend,
    highFragilityTrends: '最新正式趋势快照中脆弱性分数达到65及以上的标的数量；只统计有可用脆弱性分数的记录。分数缺失不能当作低脆弱，计数也不是总持仓风险。',
    trendBreadth: 'TRENDING（健康趋势）股票数÷快照的可排名股票数，以百分比展示。状态缺失不自动补齐或重新归一化，覆盖不足时须结合警告阅读。',
    trendParticipation: 'CANDIDATE（趋势候选）与TRENDING（健康趋势）股票数之和÷可排名股票数。WATCHING不计入此项；不是整个市场上涨股票比例。',
    deterioration: 'WEAKENING（趋势弱化）与BROKEN（结构破坏）股票数之和÷可排名股票数，以百分比展示。与当日下跌股票占比口径不同。',
  },
  crypto: cryptoHints,
  confluence: confluenceHints,
};
/** Explicit domain prevents identically named metrics (state, volume, score) sharing incorrect meanings. */
export function metricHint(scope: string | undefined, label: string): string | undefined {
  return scope ? metricHints[scope]?.[label] : undefined;
}
