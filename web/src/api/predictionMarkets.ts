import apiClient from './index';
import { toCamelCase } from './utils';

export interface PredictionTag { tagId: string; slug: string; label: string; visible: boolean; ruleGroup: string; manualVisible: boolean | null; eventCount: number }
export interface PredictionLink { symbol: string; name: string; relationType: string; relevance: string; reason: string; source: string; blocked: boolean; stale: boolean; judgedAt: string }
export interface PredictionEvent { eventId: string; title: string; description: string; url: string; tags: PredictionTag[]; endAt: string | null; closed: boolean | null; retained: boolean; ruleRetained: boolean; ruleReason: string; manualRetained: boolean | null; matchStatus: string; syncedAt: string; links: PredictionLink[] }
export interface EventPage { status: string; items: PredictionEvent[]; total: number; page: number; pageSize: number }
export interface Outcome { id: string | null; label: string; probability: number | null; priceType: string; missingReason: string | null }
export interface PredictionMarket { id: string; question: string; version: string | null; endAt: string | null; closed: boolean | null; resolved: boolean; outcomes: Outcome[] }
export interface LiveData { status: string; markets?: PredictionMarket[]; closed?: boolean; fetchedAt?: string | null; observedAt?: string | null; stale?: boolean; cacheStatus?: string; error?: string }
export interface HistoryPoint { timestamp: number; price: number; resolutionSeconds: number }
export interface HistoryData { status: string; points?: HistoryPoint[]; changes?: Record<string, { percentagePoints: number | null; reason: string | null }>; seriesAsOf?: number | null; fetchedAt?: string | null; stale?: boolean; closed?: boolean; resolved?: boolean }
export interface Filters { page: number; pageSize: number; keyword?: string; tagIds?: string[]; closed?: boolean; sort?: string }
const base = '/api/v1/prediction-markets';
async function get<T>(path: string, params: Record<string, unknown> = {}, signal?: AbortSignal): Promise<T> {
  return toCamelCase((await apiClient.get(base + path, { params, signal, paramsSerializer: { indexes: null } })).data);
}
export const predictionApi = {
  tags: (signal?: AbortSignal) => get<{ status: string; items: PredictionTag[] }>('/tags', {}, signal),
  events: (f: Filters, signal?: AbortSignal) => get<EventPage>('/events', { page: f.page, page_size: f.pageSize, keyword: f.keyword, tag_ids: f.tagIds, closed: f.closed, sort: f.sort }, signal),
  stock: (symbol: string, page: number, signal?: AbortSignal) => get<EventPage>(`/stocks/${encodeURIComponent(symbol)}`, { page, page_size: 5 }, signal),
  live: (id: string, signal?: AbortSignal) => get<LiveData>(`/events/${encodeURIComponent(id)}/live`, {}, signal),
  history: (id: string, market: string, outcome: string, window: string, signal?: AbortSignal) => get<HistoryData>(`/events/${encodeURIComponent(id)}/history`, { market_id: market, outcome_id: outcome, window }, signal),
  adminTags: (signal?: AbortSignal) => get<{ items: PredictionTag[] }>('/admin/tags', {}, signal),
  adminEvents: (page: number, keyword: string, signal?: AbortSignal) => get<EventPage>('/admin/events', { page, keyword }, signal),
  setTag: (id: string, visible: boolean | null) => apiClient.patch(`${base}/admin/tags/${encodeURIComponent(id)}`, { visible }),
  setEvent: (id: string, retained: boolean | null) => apiClient.patch(`${base}/admin/events/${encodeURIComponent(id)}`, { retained }),
  setLink: (id: string, symbol: string, action: string, reason: string) => apiClient.put(`${base}/admin/events/${encodeURIComponent(id)}/links`, { symbol, action, reason }),
  run: async (job: 'catalog' | 'matching', slug?: string, eventId?: string) => toCamelCase<{ taskId: string }>((await apiClient.post(`${base}/admin/run`, { job, slug, event_id: eventId })).data),
};
