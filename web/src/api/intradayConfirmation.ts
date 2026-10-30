import apiClient from './index';
import { toCamelCase } from './utils';
export type Market = 'CN' | 'US';
export type State = 'WAIT' | 'CONFIRMED' | 'FAILED';
export type Source = 'confluence' | 'trend' | 'etf' | 'quant';
export interface Reason { code: string; text: string }
export interface Confirmation {
  code: string; name: string; candidateSource: Source; candidateTradeDate: string;
  candidateSources?: Source[]; instrumentType?: string; currentStatus?: string; dataStatus?: string;
  conditions?: Record<string, boolean | null>; proposedState?: State;
  candidateReason: string[]; sourceGeneratedAt: string; state: State; confirmationScore: number | null; availableScoreWeight: number;
  chaseRisk: 'LOW' | 'MEDIUM' | 'HIGH' | 'UNKNOWN'; reasons: Reason[]; stateReasons: Reason[];
  metrics: Record<string, number | string | boolean | null>;
  trend: Record<string, number | string | null>;
  firstConfirmedAt: string | null; failedAt: string | null; generatedAt: string | null;
  firstConfirmedPrice?: number | null; firstConfirmedQuoteTime?: string | null;
  return3D?: number | null; return5D?: number | null; return10D?: number | null;
  currentPriceRecovered: boolean;
}
export interface Snapshot {
  market: Market; tradeDate: string; candidateTradeDate: string | null; frozenAt: string | null;
  generatedAt: string | null; status: string; warnings: string[]; items: Confirmation[];
  ruleVersion?: string;
  summary: { total: number; wait: number; confirmed: number; failed: number; everConfirmed?: number; active?: number; attention?: number }; rulesNote: string;
}
export interface Evaluation {
  evaluatedAt: string; ruleVersion: string; state: State; currentStatus: string; proposedState: State;
  confirmationScore: number | null; chaseRisk: string; dataStatus: string;
  conditions: Record<string, boolean | null>; reasons: Reason[];
  metrics: Confirmation['metrics'];
}
const base = '/api/v1/intraday-confirmation';
export const intradayConfirmationApi = {
  async read(market: Market, state?: State, source?: Source, tradeDate?: string, signal?: AbortSignal): Promise<Snapshot> {
    return toCamelCase((await apiClient.get(base, { params: { market, state, candidate_source: source, ...(tradeDate ? { trade_date: tradeDate } : {}) }, ...(signal ? { signal } : {}) })).data);
  },
  async detail(code: string, market: Market, tradeDate?: string, signal?: AbortSignal): Promise<Confirmation> {
    return toCamelCase((await apiClient.get(`${base}/${encodeURIComponent(code)}`, { params: { market, ...(tradeDate ? { trade_date: tradeDate } : {}) }, ...(signal ? { signal } : {}) })).data);
  },
  async dates(market: Market, signal?: AbortSignal): Promise<{ dates: string[] }> {
    return (await apiClient.get(`${base}/dates`, { params: { market }, ...(signal ? { signal } : {}) })).data;
  },
  async evaluations(code: string, market: Market, tradeDate?: string, signal?: AbortSignal): Promise<{ items: Evaluation[] }> {
    return toCamelCase((await apiClient.get(`${base}/${encodeURIComponent(code)}/evaluations`, { params: { market, trade_date: tradeDate }, signal })).data);
  },
  async run(market: Market): Promise<{ taskId: string }> {
    return toCamelCase((await apiClient.post(`${base}/run`, { market })).data);
  },
};
