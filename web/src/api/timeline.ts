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

export interface EarningsMetric {
  expectedValue: number | null;
  judgment: 'beat' | 'meet' | 'miss' | 'unknown';
  consensus: { value: number; quarter: string; currency: string; unit: string; basis: string | null; source: string; asOf: string | null } | null;
}
export interface EarningsOutlook {
  status: string; memberships: string[]; earningsHigh: boolean; reactionHigh: boolean;
  eps?: EarningsMetric; revenue?: EarningsMetric; guidance?: string; conclusion?: string;
  earningsConfidence?: number; earningsConfidenceReason?: string; earningsReason?: string;
  reactionConfidence?: number; reactionConfidenceReason?: string; reactionReason?: string;
  expectedClose?: number | null; expectedReturnPct?: number | null;
  intradayLow?: number | null; intradayHigh?: number | null;
  referencePrice?: number | null; referencePriceAt?: string | null; referencePriceSession?: string;
  responseDirection?: string; targetTradingDate?: string; generatedAt?: string; dataCutoff?: string;
  searchStatus?: string; stage?: string; provisional?: boolean; assumption?: string;
  missingData?: string[]; uncertainties?: string[];
  scenarios?: { name: string; conditions: string; reactionReason: string; low: number | null; high: number | null }[];
  tolerance?: { epsRelativeTolerance: number; epsAbsoluteUsd: number; revenueRelativeTolerance: number };
}
export interface EarningsDetail {
  status: string; error: string | null; summary: EarningsOutlook | null;
  actual: { status: string; predictionId: number; eps: string; revenue: string; closeError?: number;
    closeErrorPct?: number; directionCorrect?: boolean; rangeCovered?: boolean;
    actual: { eps?: {value: number; basis?: string} | null; revenue?: {value: number} | null;
      ohlc?: {open: number; high: number; low: number; close: number} | null; missingReason?: string } } | null;
  versions: { id: number; stage: string; applicability: string; generatedAt: string; dataCutoff: string;
    releaseCutoff: string; model: string; backend: string; promptVersion: string; prediction: EarningsOutlook;
    searchEvidence: {status: string; requested: boolean; configuredSupport: boolean; citations?: {url: string; title: string}[]};
    research: { sources: {sourceId: string; title: string; url: string; publisher: string; publishedAt: string | null;
      retrievedAt: string; publicationKnown: boolean; sourceType: string; supportedFacts?: string[]}[];
      facts?: {text: string; sourceIds: string[]}[];
      conflicts?: {description: string; reason: string; sourceIds: string[]}[]; uncertainties?: string[] };
  }[];
}

export interface TimelineItem {
  id: string; sourceType: 'finance_event' | 'news' | 'report'; sourceId: number;
  eventTime: string; category: Category; calendarType: CalendarType | null;
  market: string | null; title: string; summary: string;
  symbol: string | null; relatedSymbols: string[]; importance: Importance; actionability: Actionability;
  impact: string | null; impactScore: number | null; importanceScore: number | null;
  eventType: string | null; detailType: string;
  outlook?: EarningsOutlook | null;
  detailPayload: TimelineEventPayload & Record<string, unknown>;
}

export interface TimelineQuery {
  /** Cutoff: keep everything up to the end of this day in the display timezone. */
  end_date?: string;
  market?: string; category?: Category; calendar_type?: CalendarType; importance?: Importance;
  high_confidence?: boolean;
  cursor?: string; limit?: number;
}

export interface TimelineListResponse {
  items: TimelineItem[]; total: number; nextCursor: string | null; hasMore: boolean; limit: number;
}

export const timelineApi = {
  async earningsDetail(eventId: number) {
    const { data } = await apiClient.get(`/api/v1/timeline/earnings/${eventId}/outlook`);
    return toCamelCase<EarningsDetail>(data);
  },
  async refreshEarnings(eventId: number) {
    const { data } = await apiClient.post(`/api/v1/timeline/earnings/${eventId}/outlook/refresh`);
    return toCamelCase<{taskId: string; status: string}>(data);
  },
  async list(query: TimelineQuery) {
    const { data } = await apiClient.get('/api/v1/timeline', { params: { ...query, timezone: getDisplayTimezone() } });
    return toCamelCase<TimelineListResponse>(data);
  },
};
