import type { TrendState, TrendStateHistoryResponse } from '@/types/trendFollowing';

// State categories, not numeric trend scores. Keep the lifecycle ordering in the legend.
export const STATE_COLORS: Record<TrendState, { light: string; dark: string }> = {
  IDLE: { light: '#a1a1aa', dark: '#71717a' },
  WATCHING: { light: '#93c5fd', dark: '#608fbd' },
  CANDIDATE: { light: '#5eead4', dark: '#2dd4bf' },
  TRENDING: { light: '#22a565', dark: '#22a565' },
  WEAKENING: { light: '#facc15', dark: '#eab308' },
  BROKEN: { light: '#ef4444', dark: '#f87171' },
};
export const HEATMAP_STATES = Object.keys(STATE_COLORS) as TrendState[];

export function stateTooltip(data: TrendStateHistoryResponse, x: number, y: number): string {
  const stock = data.items[y];
  if (!stock) return '';
  const day = data.dates[x];
  const header = `${day}${day === data.previewDate ? ' · Preview' : ''}\n${stock.code} / ${stock.name}`;
  const cell = stock.history[x];
  if (!cell) return `${header}\n暂无 Snapshot`;
  const score = (value: number | null) => value == null ? '—' : value.toFixed(1);
  return `${header}\nRank: #${cell.rank}\nState: ${cell.state}\nAlpha Score: ${score(cell.alphaScore)}\nTrend Score: ${score(cell.trendScore)}\nRS Score: ${score(cell.rsScore)}\nFragility: ${score(cell.fragilityScore)}\n持续天数: ${cell.trendDurationDays ?? '—'}`;
}
