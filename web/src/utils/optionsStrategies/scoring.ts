import type { DailyBar } from '@/api/marketData';
import { dailyPatternMarketDate } from '@/utils/dailyPatterns';
import { OPTION_STRATEGIES, type OptionStrategy, type StrategyProfile } from './catalog';

export type StrategyHorizon = 'short' | 'swing';
export const HORIZONS = { short: { label: '短线', sessions: 5 }, swing: { label: '波段', sessions: 10 } } as const;
export interface TrendObservation {
  status: 'ready' | 'unavailable'; reason: string | null; horizon: StrategyHorizon; sessions: number;
  asOf: string | null; startDate: string | null; preview: boolean; count: number;
  returnPct: number | null; slopePct: number | null; efficiency: number | null; atrPct: number | null;
  direction: number | null; location: number | null; label: string;
}
export interface StrategyFit extends OptionStrategy {
  score: number | null; reasons: string[]; breakdown: { direction: number; continuity: number; location: number } | null;
}
const clamp = (value: number, low = 0, high = 1) => Math.max(low, Math.min(high, value));
const pct = (value: number) => `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;
function validBar(bar: DailyBar) {
  return [bar.open, bar.high, bar.low, bar.close].every(value => Number.isFinite(value) && value > 0)
    && bar.low <= Math.min(bar.open, bar.close) && bar.high >= Math.max(bar.open, bar.close)
    && bar.high >= bar.low && !(Number.isFinite(bar.volume) && bar.volume <= 0);
}
export function observeTrend(input: readonly DailyBar[], market: string, horizon: StrategyHorizon,
  endDate?: string, now = new Date()): TrendObservation {
  const sessions = HORIZONS[horizon].sessions;
  const empty: TrendObservation = { status: 'unavailable', reason: null, horizon, sessions,
    asOf: null, startDate: null, preview: false, count: 0, returnPct: null, slopePct: null,
    efficiency: null, atrPct: null, direction: null, location: null, label: '数据不足' };
  const today = dailyPatternMarketDate(market, now);
  if (!today) return { ...empty, reason: '无法确定标的市场日期，暂不评分。' };
  const cutoff = endDate && endDate < today ? endDate : today;
  // Keep invalid / conflicting recent observations in the window; never compress them into adjacent sessions.
  const byDate = new Map<string, { bar: DailyBar; conflict: boolean }>();
  for (const bar of input) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(bar.tradeDate) || bar.tradeDate > cutoff) continue;
    const old = byDate.get(bar.tradeDate);
    const conflict = old && ['open', 'high', 'low', 'close', 'volume'].some(key => old.bar[key as keyof DailyBar] !== bar[key as keyof DailyBar]);
    byDate.set(bar.tradeDate, { bar, conflict: Boolean(old?.conflict || conflict) });
  }
  const rows = [...byDate.values()].sort((a, b) => a.bar.tradeDate.localeCompare(b.bar.tradeDate)).slice(-sessions - 1);
  const bars = rows.map(row => row.bar);
  const asOf = bars.at(-1)?.tradeDate ?? null;
  const base = { ...empty, asOf, startDate: bars[0]?.tradeDate ?? null, count: bars.length, preview: asOf === today };
  if (rows.length < sessions + 1) return { ...base, reason: `至少需要 ${sessions + 1} 根有效日K，当前仅有 ${rows.length} 根。` };
  if (rows.some(row => row.conflict)) return { ...base, reason: '观察窗口存在同交易日价格冲突，暂不评分。' };
  if (bars.some(bar => !validBar(bar))) return { ...base, reason: '观察窗口存在无效价格或零成交量日K，暂不评分。' };
  const first = bars[0]!, last = bars.at(-1)!;
  const returnPct = last.close / first.close - 1;
  const path = bars.slice(1).reduce((sum, bar, index) => sum + Math.abs(bar.close - bars[index]!.close), 0);
  const efficiency = path > 0 ? Math.abs(last.close - first.close) / path : 0;
  const atr = bars.slice(1).reduce((sum, bar, index) => sum + Math.max(bar.high - bar.low,
    Math.abs(bar.high - bars[index]!.close), Math.abs(bar.low - bars[index]!.close)), 0) / sessions;
  const atrPct = atr / last.close;
  const meanX = sessions / 2, logs = bars.map(bar => Math.log(bar.close));
  const meanY = logs.reduce((a, b) => a + b, 0) / logs.length;
  const slope = logs.reduce((sum, value, index) => sum + (index - meanX) * (value - meanY), 0)
    / logs.reduce((sum, _value, index) => sum + (index - meanX) ** 2, 0);
  const scale = Math.max(atrPct * Math.sqrt(sessions), .000001);
  const direction = .6 * clamp(returnPct / scale, -1, 1) + .4 * clamp(slope * sessions / scale, -1, 1);
  const high = Math.max(...bars.map(bar => bar.high)), low = Math.min(...bars.map(bar => bar.low));
  const location = high > low ? clamp((last.close - low) / (high - low)) : .5;
  const label = direction >= .55 ? '上行趋势' : direction >= .15 ? '温和偏多'
    : direction <= -.55 ? '下行趋势' : direction <= -.15 ? '温和偏空' : '区间震荡';
  return { ...base, status: 'ready', reason: null, returnPct, slopePct: Math.expm1(slope),
    efficiency, atrPct, direction, location, label };
}
function directionFit(profile: StrategyProfile, bias: number) {
  switch (profile) {
    case 'bull': case 'hedgeShort': return (bias + 1) / 2;
    case 'bear': case 'hedgeLong': return (1 - bias) / 2;
    case 'mildBull': case 'calendarBull': return clamp(1 - Math.abs(bias - .25) / 1.25);
    case 'mildBear': case 'calendarBear': return clamp(1 - Math.abs(bias + .25) / 1.25);
    case 'range': return 1 - Math.abs(bias);
    case 'move': return Math.abs(bias);
    case 'arbitrage': return 0;
  }
}
export function scoreStrategies(observation: TrendObservation): StrategyFit[] {
  return OPTION_STRATEGIES.map(strategy => {
    if (strategy.profile === 'arbitrage') return { ...strategy, score: null, breakdown: null,
      reasons: ['套利与融资主要取决于同步期权报价、平价关系、利率和交易成本，无法由K线趋势评分。'] };
    if (observation.status !== 'ready') return { ...strategy, score: null, breakdown: null,
      reasons: [observation.reason ?? '缺少可用日K，暂不评分。'] };
    const bias = observation.direction!, efficiency = observation.efficiency!, location = observation.location!;
    const directional = ['bull', 'bear', 'hedgeLong', 'hedgeShort', 'move'].includes(strategy.profile);
    const continuity = directional ? efficiency : 1 - efficiency * .65;
    const bullish = ['bull', 'mildBull', 'calendarBull', 'hedgeShort'].includes(strategy.profile);
    const bearish = ['bear', 'mildBear', 'calendarBear', 'hedgeLong'].includes(strategy.profile);
    const position = bullish ? location : bearish ? 1 - location
      : strategy.profile === 'range' ? 1 - Math.abs(location - .5) * 2 : Math.abs(location - .5) * 2;
    const breakdown = { direction: directionFit(strategy.profile, bias) * 60, continuity: continuity * 25, location: position * 15 };
    const score = Math.round(clamp(breakdown.direction + breakdown.continuity + breakdown.location, 0, 100));
    const reasons = [
      `近${observation.sessions}个交易日${pct(observation.returnPct!)}，${observation.label}；趋势延续性 ${(efficiency * 100).toFixed(0)}/100。`,
      `${strategy.outlook}${breakdown.direction >= 42 ? '当前方向较匹配。' : breakdown.direction < 24 ? '当前方向存在明显冲突。' : '当前方向仅部分匹配。'}`,
    ];
    if (strategy.profile === 'move') reasons.push('近期移动仅作形态参考，不能据此确认未来波动足以覆盖权利金。');
    if (strategy.profile === 'hedgeLong') reasons.push('前提是已有或同步建立多头；本页未读取真实持仓。');
    if (strategy.profile === 'hedgeShort') reasons.push('前提是已有空头；本页未核验融券及真实持仓。');
    if (strategy.category === '日历与对角') reasons.push('近远月IV与期限定价未纳入，必须另行核验。');
    return { ...strategy, score, breakdown, reasons };
  }).sort((a, b) => a.score === null ? b.score === null ? a.id.localeCompare(b.id) : 1
    : b.score === null ? -1 : b.score - a.score || a.id.localeCompare(b.id));
}
