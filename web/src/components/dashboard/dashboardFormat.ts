import type { ETFChange, ETFRankingChanges } from '@/types/etfRotation';
import type { TimelineItem } from '@/api/timeline';
import { dayKey, formatEps, sessionLabel } from '@/components/timeline/timelineFormat';

import { enumLabel } from '@/i18n/labels';

/** @deprecated Prefer BilingualEnum; kept for callers needing plain Chinese. */
export const regimeText = (value?: string | null) => enumLabel(value).zh;
export function regimeTone(value?: string | null) {
  return ['RISK_ON', 'risk_on', 'BULL'].includes(value ?? '') ? 'text-market-up'
    : ['RISK_OFF', 'risk_off', 'BEAR'].includes(value ?? '') ? 'text-market-down' : 'text-muted-foreground';
}
export function etfHighlights(changes?: ETFRankingChanges | null): ETFChange[] {
  const seen = new Set<string>();
  return [...(changes?.newBuys ?? []), ...(changes?.newExits ?? [])].filter(change => {
    if (seen.has(change.code)) return false;
    seen.add(change.code);
    return true;
  }).slice(0, 3);
}
export function upcomingEvents(items: TimelineItem[], now: Date) {
  const today = dayKey(now.toISOString());
  return items.filter(item => item.category === 'event' && ['earnings', 'macro'].includes(item.calendarType ?? '')
    && (item.detailPayload.allDay ? dayKey(item.eventTime) >= today : Date.parse(item.eventTime) >= now.getTime())).slice(0, 8);
}
export function feedSummary(item: TimelineItem) {
  if (item.calendarType === 'earnings') {
    const eps = formatEps(item.detailPayload.epsEstimate, item.detailPayload.currency);
    return [item.detailPayload.reportingPeriod, eps ? `EPS 预期 ${eps}` : '', sessionLabel(item.detailPayload.marketSession)].filter(Boolean).join(' · ');
  }
  return item.summary;
}
