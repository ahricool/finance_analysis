import apiClient from './index';
import { toCamelCase } from './utils';
import { getDisplayTimezone } from '@/utils/format';

export type Importance = 'low' | 'normal' | 'high' | 'critical';
export type Actionability = 'none' | 'watch' | 'consider' | 'action_required';
export type Category = 'event' | 'news' | 'analysis';
export type CalendarType = 'earnings' | 'macro';
export type TimelineTab = 'all' | 'earnings' | 'macro' | 'news' | 'analysis';

export interface TimelineEventPayload {
  content?: string;
  allDay?: boolean;
  eventDate?: string | null;
  counterName?: string | null;
  marketSession?: string | null;
  reportingPeriod?: string | null;
  currency?: string | null;
  provider?: string | null;
  sourceProviders?: string[];
  epsEstimate?: number | null;
  reportedEps?: number | null;
  epsSurprisePct?: number | null;
  importanceReason?: string | null;
  tradingDaysToEvent?: number | null;
}

export interface TimelineItem {
  id: string; sourceType: 'finance_event' | 'news' | 'report'; sourceId: number;
  eventTime: string; category: Category; calendarType: CalendarType | null;
  market: string | null; title: string; summary: string;
  symbol: string | null; relatedSymbols: string[]; importance: Importance; actionability: Actionability;
  impact: string | null; impactScore: number | null; importanceScore: number | null;
  eventType: string | null; detailType: string;
  detailPayload: TimelineEventPayload & Record<string, unknown>;
}

export interface TimelineQuery {
  /** Cutoff: keep everything up to the end of this day in the display timezone. */
  end_date?: string;
  market?: string; category?: Category; calendar_type?: CalendarType; importance?: Importance;
  cursor?: string; limit?: number;
}

export interface TimelineListResponse {
  items: TimelineItem[]; total: number; nextCursor: string | null; hasMore: boolean; limit: number;
}

export const timelineApi = {
  async list(query: TimelineQuery) {
    const { data } = await apiClient.get('/api/v1/timeline', { params: { ...query, timezone: getDisplayTimezone() } });
    return toCamelCase<TimelineListResponse>(data);
  },
};
