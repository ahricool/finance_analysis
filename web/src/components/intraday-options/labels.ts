import type { IntradayOptionRow, TrendDirection, TrendStage } from '@/api/intradayOptions';

export const directions: Record<TrendDirection, string> = {
  bullish: '偏多', bearish: '偏空', neutral: '震荡', conflict: '分歧',
};
export const stages: Record<TrendStage, string> = {
  continuing: '趋势持续', pullback: '回撤观察', extended: '短线延伸', conflict: '方向分歧', waiting: '等待方向',
};
export const dataLabels: Record<IntradayOptionRow['dataStatus'], string> = {
  ready: '', waiting: '等待采集', warming: '窗口预热', gap: '分钟缺失', delayed: '分钟行情延迟', invalid_time: '时间异常',
};
export const directionOrder = { bullish: 4, bearish: 3, conflict: 2, neutral: 1 };
export const stageOrder = { continuing: 5, pullback: 4, extended: 3, conflict: 2, waiting: 1 };
export function usable(row: IntradayOptionRow) { return ['ready', 'warming', 'gap'].includes(row.dataStatus); }
export function fmt(value: number | null | undefined, digits = 1) {
  return value == null ? '—' : value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
export function pct(value: number | null | undefined) { return value == null ? '—' : `${value > 0 ? '+' : ''}${fmt(value, 2)}%`; }
export function tone(value: number | null | undefined) { return value == null || value === 0 ? '' : value > 0 ? 'text-market-up' : 'text-market-down'; }
export function clock(value: string | null | undefined) {
  return value ? new Date(value).toLocaleTimeString('zh-CN', { timeZone: 'America/New_York', hour12: false }) : '—';
}
