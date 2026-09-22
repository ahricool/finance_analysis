import apiClient from './index';
import { toCamelCase } from './utils';

export type Market = 'CN' | 'US';
export type SignalKey = 'industry' | 'trend' | 'quant' | 'etf' | 'dragonTiger';
export interface ConfluenceSignal {
  sourceModule: string; status: 'positive' | 'neutral' | 'negative' | 'unavailable';
  weight: number; score: number | null; tradeDate: string | null; sourceGeneratedAt: string | null;
  evidence: Record<string, unknown>; reasons: string[];
}
export interface ConfluenceItem {
  instrumentId: number; code: string; name: string; confluenceScore: number | null;
  availableWeight: number; availableSignalCount: number; positiveSignalCount: number;
  eligible: boolean; strongConfluence: boolean; signals: Record<SignalKey, ConfluenceSignal>;
  reasons: string[]; generatedAt: string;
}
export interface ConfluenceRanking {
  market: Market; tradeDate: string | null; generatedAt: string | null; algorithmVersion: string | null;
  sourceAvailability: Record<SignalKey, { status: string; count: number; tradeDate: string | null; reason?: string }>;
  summary: { total: number; eligible: number; strongConfluence: number; ignitionIndustryStrong: number; topIndustryConfluence: number };
  rules: { minSignals: number; strongMinSignals: number; strongMinPositive: number; strongMinScore: number };
  total: number; items: ConfluenceItem[];
}
export interface RankingParams {
  market: Market; trade_date?: string; min_score?: number; min_signals?: number; industry?: string;
  lifecycle?: string; early_only?: boolean; top_industry?: boolean; strong_only?: boolean; limit?: number;
}
const base = '/api/v1/confluence';
export const confluenceApi = {
  async ranking(params: RankingParams): Promise<ConfluenceRanking> {
    return toCamelCase((await apiClient.get(`${base}/ranking`, { params })).data);
  },
  async dates(market: Market): Promise<string[]> { return (await apiClient.get(`${base}/dates`, { params: { market } })).data; },
  async detail(code: string, market: Market, tradeDate: string): Promise<{ market: Market; tradeDate: string; algorithmVersion: string; item: ConfluenceItem }> {
    return toCamelCase((await apiClient.get(`${base}/${encodeURIComponent(code)}`, { params: { market, trade_date: tradeDate } })).data);
  },
  async run(market: Market, tradeDate?: string): Promise<{ taskId: string }> {
    return toCamelCase((await apiClient.post(`${base}/run`, { market, trade_date: tradeDate })).data);
  },
};
