import { forwardReturnColumns } from '@/composables/useForwardReturns';
import type { TrendRankingSnapshot } from '@/types/trendFollowing';
import { trendIndicatorDescriptions } from './indicatorDescriptions';

// Column, filter and state-label definitions for the three trend ranking tables.
export const trendColumns = [
  { key: 'rank', label: 'alphaRank', group: 'Core', format: 'number', description: trendIndicatorDescriptions.rank },
  { key: 'name', label: '股票名称', group: 'Core', format: 'text', description: undefined },
  { key: 'state', label: 'state', group: 'Core', format: 'text', description: trendIndicatorDescriptions.state },
  { key: 'alphaScore', label: 'alphaScore', group: 'Core', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'entryScore', label: 'entryScore', group: 'Core', format: 'score', description: trendIndicatorDescriptions.entry },
  { key: 'entryType', label: 'entryType', group: 'Core', format: 'text', description: trendIndicatorDescriptions.entry },
  { key: 'trendScore', label: 'trendScore', group: 'Core', format: 'score', description: trendIndicatorDescriptions.trend },
  { key: 'rsScore', label: 'rsScore', group: 'Core', format: 'score', description: trendIndicatorDescriptions.relativeStrength },
  { key: 'setupScore', label: 'setupScore', group: 'Core', format: 'score', description: trendIndicatorDescriptions.breakout },
  { key: 'pathScore', label: 'pathScore', group: 'Core', format: 'score', description: trendIndicatorDescriptions.path },
  { key: 'distanceFromMa20', label: 'distanceFromMa20', group: 'Core', format: 'percent', description: trendIndicatorDescriptions.distanceFromMa20 },
  { key: 'atrPercent', label: 'atrPercent', group: 'Core', format: 'percent', description: trendIndicatorDescriptions.atrPercent },
  { key: 'fragilityScore', label: 'fragility', group: 'Core', format: 'score', description: trendIndicatorDescriptions.fragility },
  { key: 'closeLocationValue', label: 'clv', group: 'Core', format: 'ratio', description: trendIndicatorDescriptions.clv },
  ...forwardReturnColumns,
  { key: 'trendLifecycle', label: 'lifecycleAge', group: 'Core', format: 'number', description: trendIndicatorDescriptions.lifecycle },
  { key: 'rankChange5D', label: '排名趋势', group: 'Core', format: 'number', description: trendIndicatorDescriptions.rankChange },
  { key: 'referencePrice', label: 'referencePrice', group: 'Core', format: 'price', description: trendIndicatorDescriptions.reference },
  { key: 'alphaTrendContribution', label: 'Trend Contribution', group: 'Alpha', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'alphaRsContribution', label: 'RS Contribution', group: 'Alpha', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'alphaSetupContribution', label: 'Setup Contribution', group: 'Alpha', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'alphaPathContribution', label: 'Path Contribution', group: 'Alpha', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'weightedSlopePercentile', label: 'Slope Percentile 20D', group: 'Trend', format: 'score', description: trendIndicatorDescriptions.slopePercentile },
  { key: 'r2Quality', label: 'R² Quality', group: 'Trend', format: 'score', description: trendIndicatorDescriptions.r2Quality },
  { key: 'momentumQuality', label: 'Momentum Quality', group: 'Trend', format: 'score', description: trendIndicatorDescriptions.momentumQuality },
  { key: 'return10DQuality', label: 'Return 10D Quality', group: 'Trend', format: 'score', description: trendIndicatorDescriptions.returnQuality },
  { key: 'return20DQuality', label: 'Return 20D Quality', group: 'Trend', format: 'score', description: trendIndicatorDescriptions.returnQuality },
  { key: 'drawdownQuality', label: 'Drawdown Quality', group: 'Trend', format: 'score', description: trendIndicatorDescriptions.drawdownQuality },
  { key: 'rs5DQuality', label: 'RS 5D Quality', group: 'RS', format: 'score', description: trendIndicatorDescriptions.rsQuality },
  { key: 'rs10DQuality', label: 'RS 10D Quality', group: 'RS', format: 'score', description: trendIndicatorDescriptions.rsQuality },
  { key: 'rs20DQuality', label: 'RS 20D Quality', group: 'RS', format: 'score', description: trendIndicatorDescriptions.rsQuality },
  { key: 'breakoutQuality', label: 'Breakout Quality', group: 'Setup', format: 'score', description: trendIndicatorDescriptions.breakout },
  { key: 'extensionQuality', label: 'Extension Quality', group: 'Setup', format: 'score', description: trendIndicatorDescriptions.breakout },
  { key: 'volumeQuality', label: 'Volume Quality', group: 'Setup', format: 'score', description: trendIndicatorDescriptions.breakout },
  { key: 'compressionQuality', label: 'Compression Quality', group: 'Setup', format: 'score', description: trendIndicatorDescriptions.breakout },
  { key: 'concentrationQuality', label: 'Concentration Quality', group: 'Path', format: 'score', description: trendIndicatorDescriptions.concentration },
  { key: 'volatilityQuality', label: 'Volatility Quality', group: 'Path', format: 'score', description: trendIndicatorDescriptions.expansion },
  { key: 'downsideControlQuality', label: 'Downside Control Quality', group: 'Path', format: 'score', description: trendIndicatorDescriptions.downside },
  { key: 'setup', label: 'Setup', group: 'Signals / Explain', format: 'text', description: trendIndicatorDescriptions.setup },
  { key: 'trendCandidate', label: 'Trend Candidate', group: 'Signals / Explain', format: 'boolean', description: trendIndicatorDescriptions.candidate },
  { key: 'priorCompression', label: 'Prior Compression', group: 'Signals / Explain', format: 'boolean', description: trendIndicatorDescriptions.volumeCompression },
  { key: 'compressionBreakout', label: 'Compression Breakout', group: 'Signals / Explain', format: 'boolean', description: trendIndicatorDescriptions.setup },
  { key: 'trendResume', label: 'Trend Resume', group: 'Signals / Explain', format: 'boolean', description: trendIndicatorDescriptions.trendResume },
  { key: 'signedEfficiencyRatio10D', label: 'Signed Efficiency 10D', group: 'Signals / Explain', format: 'score', description: trendIndicatorDescriptions.signedEfficiency },
  { key: 'rawWeightedSlope', label: 'Weighted Slope 20D', group: 'Signals / Explain', format: 'slope', description: trendIndicatorDescriptions.weightedSlope },
  { key: 'weightedR2', label: 'Weighted R²', group: 'Signals / Explain', format: 'r2', description: trendIndicatorDescriptions.r2 },
  { key: 'return5D', label: '5D Return', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.return },
  { key: 'return10D', label: '10D Return', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.return },
  { key: 'return20D', label: '20D Return', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.return },
  { key: 'drawdown20D', label: 'Drawdown 20D', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.drawdown },
  { key: 'rs5D', label: 'RS 5D', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.rawRelativeStrength },
  { key: 'rs10D', label: 'RS 10D', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.rawRelativeStrength },
  { key: 'rs20D', label: 'RS 20D', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.rawRelativeStrength },
  { key: 'volumeRatio', label: 'Volume Ratio', group: 'Signals / Explain', format: 'score', description: trendIndicatorDescriptions.volumeCompression },
  { key: 'positiveReturnConcentration', label: 'Return Concentration', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.concentration },
  { key: 'atrExpansionRatio', label: 'ATR Expansion', group: 'Signals / Explain', format: 'ratio', description: trendIndicatorDescriptions.expansion },
  { key: 'downsideUpsideRatio', label: 'Downside / Upside', group: 'Signals / Explain', format: 'ratio', description: trendIndicatorDescriptions.downside },
  { key: 'ma10', label: 'MA10', group: 'Signals / Explain', format: 'score', description: trendIndicatorDescriptions.movingAverage },
  { key: 'ma20', label: 'MA20', group: 'Signals / Explain', format: 'score', description: trendIndicatorDescriptions.movingAverage },
  { key: 'ma10Slope', label: 'MA10 Slope', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.maSlope },
  { key: 'ma20Slope', label: 'MA20 Slope', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.maSlope },
  { key: 'trendAcceleration', label: 'Trend Acceleration', group: 'Risk / Health', format: 'score', description: trendIndicatorDescriptions.trendAcceleration },
] as const;
export const boxColumns = [
  { key: 'name', label: '股票名称', format: 'text' },
  { key: 'boxState', label: '状态', format: 'text', description: trendIndicatorDescriptions.boxState },
  { key: 'boxQuality', label: 'boxQuality', format: 'score', description: trendIndicatorDescriptions.boxQuality },
  { key: 'boxWindowDays', label: 'boxDays', format: 'number', description: trendIndicatorDescriptions.boxWindowDays },
  { key: 'boxWidthPct', label: 'boxWidth', format: 'percent', description: trendIndicatorDescriptions.boxWidthPct },
  { key: 'distanceToBoxHighPct', label: '距箱顶', format: 'percent', description: trendIndicatorDescriptions.distanceToBoxHighPct },
  { key: 'boxBreakoutDistanceAtr', label: '突破距离', format: 'ratio', description: trendIndicatorDescriptions.boxBreakoutDistanceAtr },
  { key: 'boxUpperTouches', label: '上沿测试', format: 'number', description: trendIndicatorDescriptions.boxUpperTouches },
  { key: 'rsScore', label: 'rsScore', format: 'score', description: trendIndicatorDescriptions.relativeStrength },
  { key: 'trendScore', label: 'trendScore', format: 'score', description: trendIndicatorDescriptions.trend },
  { key: 'alphaScore', label: 'alpha', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'volumeRatio', label: 'volume', format: 'ratio', description: trendIndicatorDescriptions.volumeCompression },
  ...forwardReturnColumns,
] as const;
export const mrColumns = [
  { key: 'name', label: '股票名称', format: 'text' },
  { key: 'mrState', label: 'mrState', format: 'text', description: trendIndicatorDescriptions.mrState },
  { key: 'mrQuality', label: 'mrQuality', format: 'score', description: trendIndicatorDescriptions.mrQuality },
  { key: 'rsi14', label: 'RSI20', format: 'score', description: trendIndicatorDescriptions.rsi14 },
  { key: 'distanceFromMa20Atr', label: '距 MA20 / ATR', format: 'ratio', description: trendIndicatorDescriptions.distanceFromMa20Atr },
  { key: 'return3D', label: 'return3D', format: 'percent', description: trendIndicatorDescriptions.return },
  { key: 'return5D', label: 'return5D', format: 'percent', description: trendIndicatorDescriptions.return },
  { key: 'closeLocationValue', label: 'clv', format: 'ratio', description: trendIndicatorDescriptions.clv },
  { key: 'trendScore', label: 'trendScore', format: 'score', description: trendIndicatorDescriptions.trend },
  { key: 'rsScore', label: 'rsScore', format: 'score', description: trendIndicatorDescriptions.relativeStrength },
  { key: 'alphaScore', label: 'alpha', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'state', label: 'state', format: 'text', description: trendIndicatorDescriptions.state },
] as const;
export const mrFilters = [{ value: 'all', label: '全部超跌机会' }, { value: 'MR_REBOUND', label: '反弹确认' }, { value: 'MR_OVERSOLD', label: '超跌观察' }];
export const mrText = (value: unknown) => value === 'MR_REBOUND' ? '反弹确认' : value === 'MR_OVERSOLD' ? '超跌观察' : value === 'MR_NONE' ? '无超跌机会' : '—';
export const mrPriority = (row: TrendRankingSnapshot) => row.features.mrState === 'MR_REBOUND' ? 0 : row.features.mrState === 'MR_OVERSOLD' ? 1 : 2;
export type ColumnSource = typeof trendColumns[number] | typeof boxColumns[number] | typeof mrColumns[number];
export type RankingColumn = { key: ColumnSource['key']; label: string; format: ColumnSource['format']; group: string; description?: string };
export type SortKey = RankingColumn['key'];
export const boxFilters = [
  { value: 'opportunities', label: '全部机会' }, { value: 'BOX_BREAKOUT', label: '刚突破' },
  { value: 'BOX_READY', label: '待突破' }, { value: 'BOX_FORMING', label: '形成中' },
];
export function boxStateText(state: unknown) {
  return state === 'BOX_BREAKOUT' ? '刚突破' : state === 'BOX_READY' ? '待突破' : state === 'BOX_FORMING' ? '整理中' : state === 'NONE' ? '无结构机会' : '—';
}
export const boxPriority = (item: TrendRankingSnapshot) => item.features.boxState === 'BOX_BREAKOUT' ? 0
  : item.features.boxState === 'BOX_READY' ? 1 : item.features.boxState === 'BOX_FORMING' ? 2 : 3;
export function defaultBoxSort(left: TrendRankingSnapshot, right: TrendRankingSnapshot) {
  return boxPriority(left) - boxPriority(right)
    || (right.features.boxQuality ?? -1) - (left.features.boxQuality ?? -1)
    || right.alphaScore - left.alphaScore || left.code.localeCompare(right.code);
}
export type StateFilter = 'all' | 'CANDIDATE' | 'TRENDING' | 'WEAKENING' | 'BROKEN';
export const stateFilters: Array<{ value: StateFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'CANDIDATE', label: '趋势候选' },
  { value: 'TRENDING', label: '趋势健康' },
  { value: 'WEAKENING', label: '趋势弱化' },
  { value: 'BROKEN', label: '趋势破坏' },
];
