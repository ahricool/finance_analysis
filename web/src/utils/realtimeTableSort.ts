import { opportunityKinds } from '@/components/intraday-options/labels';
import type { RealtimeConnectionStatus, RealtimeQuote, RealtimeTrend, RealtimePatternState } from '@/api/realtimeMarket';

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

export function currentStockOpportunity(quote: RealtimeQuote | undefined, now: Date, status: RealtimeConnectionStatus) {
  const opportunity = quote?.opportunity;
  if ((status !== 'connected' && status !== 'sse') || opportunity?.qualityScore == null || !quote?.eventTime || !quote.receivedAt || !quote.trend1m?.barTime) return null;
  const stamp = now.getTime();
  const barAge = stamp - Date.parse(quote.trend1m.barTime) - 60_000;
  return barAge >= 0 && barAge < 75_000 && stamp < Date.parse(opportunity.expiresAt)
    && stamp - Math.min(Date.parse(quote.eventTime), Date.parse(quote.receivedAt)) <= 30_000 ? opportunity : null;
}

export function stockOpportunityText(quote: RealtimeQuote | undefined, now: Date, status: RealtimeConnectionStatus) {
  const opportunity = currentStockOpportunity(quote, now, status);
  return opportunity ? `${opportunity.qualityScore?.toFixed(0)}分 · ${opportunityKinds[opportunity.kind]} · ${opportunity.direction === 'bullish' ? '偏多' : '偏空'}` : '—';
}
