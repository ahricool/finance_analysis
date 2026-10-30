import type { RealtimeTrend, RealtimePatternState } from '@/api/realtimeMarket';

export function trendSortValue(trend: RealtimeTrend | null | undefined): number | null {
  if (!trend || trend.state === 'insufficient' || trend.streak <= 0) return null;
  if (trend.state === 'above') return trend.streak;
  if (trend.state === 'below') return -trend.streak;
  return 0;
}

export function patternSortValue(pattern: RealtimePatternState | null | undefined): number | null {
  const signal = pattern?.status === 'active' ? pattern.signal : null;
  if (!signal) return null;
  const stage = { forming: 1, warning: 2, confirmed: 3 }[signal.stage];
  const direction = ['bullish_continuation', 'bearish_to_bullish', 'bullish_breakout'].includes(
    signal.direction,
  )
    ? 1
    : ['bearish_continuation', 'bullish_to_bearish', 'bearish_breakout'].includes(signal.direction)
      ? -1
      : 0;
  return stage * 1000 + signal.qualityScore * 10 + direction;
}
