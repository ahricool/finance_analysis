import apiClient from './index';
import { toCamelCase } from './utils';

export interface PredictionEvent { eventId: string; title: string; url: string; endAt: string | null; closed: boolean | null; volume24H: number | null }
export interface SearchResult { status: string; symbol?: string; queries: string[]; items: PredictionEvent[]; partial: boolean; fetchedAt: string | null; stale: boolean; cacheStatus: string }
export interface Outcome { id: string | null; label: string; probability: number | null; priceType: string; missingReason: string | null }
export interface PredictionMarket { id: string; question: string; version: string | null; endAt: string | null; closed: boolean | null; resolved: boolean; outcomes: Outcome[] }
export interface LiveData { status: string; markets?: PredictionMarket[]; closed?: boolean; fetchedAt?: string | null; observedAt?: string | null; stale?: boolean; cacheStatus?: string; error?: string }
export interface HistoryPoint { timestamp: number; price: number; resolutionSeconds: number }
export interface HistoryData { status: string; points?: HistoryPoint[]; changes?: Record<string, { percentagePoints: number | null; reason: string | null }>; seriesAsOf?: number | null; fetchedAt?: string | null; stale?: boolean; closed?: boolean; resolved?: boolean }

const base = '/api/v1/prediction-markets';
async function get<T>(path: string, params: Record<string, unknown> = {}, signal?: AbortSignal): Promise<T> {
  return toCamelCase((await apiClient.get(base + path, { params, signal })).data);
}
export const predictionApi = {
  search: (symbol: string, signal?: AbortSignal) => get<SearchResult>(`/stocks/${encodeURIComponent(symbol)}`, {}, signal),
  live: (id: string, signal?: AbortSignal) => get<LiveData>(`/events/${encodeURIComponent(id)}/live`, {}, signal),
  history: (id: string, market: string, outcome: string, window: string, signal?: AbortSignal) => get<HistoryData>(`/events/${encodeURIComponent(id)}/history`, { market_id: market, outcome_id: outcome, window }, signal),
};
