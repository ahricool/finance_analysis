import type { IntradayOptionRow, IntradayStructure, TrendDirection, TrendStage } from '@/api/intradayOptions';

export const directions: Record<TrendDirection, string> = {
  bullish: '偏多', bearish: '偏空', neutral: '震荡', conflict: '分歧',
};
export const stages: Record<TrendStage, string> = {
  continuing: '趋势持续', pullback: '回撤观察', extended: '短线延伸', conflict: '方向分歧', waiting: '等待方向',
};
export const dataLabels: Record<IntradayOptionRow['dataStatus'], string> = {
  ready: '', waiting: '等待采集', warming: '开盘不足 · 数据不全', gap: '分钟缺失', delayed: '分钟行情延迟', invalid_time: '时间异常',
};
export const directionOrder = { bullish: 4, bearish: 3, conflict: 2, neutral: 1 };
export const stageOrder = { continuing: 5, pullback: 4, extended: 3, conflict: 2, waiting: 1 };
export function usable(row: IntradayOptionRow) { return ['ready', 'warming', 'gap', 'delayed'].includes(row.dataStatus); }
export function fmt(value: number | null | undefined, digits = 1) {
  return value == null ? '—' : value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
export function pct(value: number | null | undefined) { return value == null ? '—' : `${value > 0 ? '+' : ''}${fmt(value, 2)}%`; }
export function tone(value: number | null | undefined) { return value == null || value === 0 ? '' : value > 0 ? 'text-market-up' : 'text-market-down'; }
export function clock(value: string | null | undefined) {
  return value ? new Date(value).toLocaleTimeString('zh-CN', { timeZone: 'America/New_York', hour12: false }) : '—';
}

export const structureLabels: Record<IntradayStructure['kind'], string> = {
  uptrend: '持续走强', downtrend: '持续走弱', range: '震荡横盘', breakout_up: '箱体向上突破', breakout_down: '箱体向下突破',
  failed_up: '向上突破失败', failed_down: '向下突破失败', rebound: '下跌后反弹', pullback: '上涨后回落', unclear: '结构不明确',
};
export const structurePhases: Record<IntradayStructure['phase'], string> = {
  waiting: '等待结构', forming: '待确认', confirmed: '已确认', retest: '回踩守住', failed: '已失效',
  continuing: '延续中', pullback: '回撤观察', pausing: '短线停顿', inside: '区间内', warming: '结构预热',
};
export function structureName(value: IntradayStructure | null | undefined) {
  return value ? value.oversold && value.kind === 'rebound' ? '超跌反弹' : structureLabels[value.kind] : '—';
}
