import apiClient from './index';
import { toCamelCase } from './utils';
export type Market = 'CN' | 'US';
export type State = 'WAIT' | 'CONFIRMED' | 'FAILED';
export type Source = 'confluence' | 'trend' | 'quant';
export interface Reason { code: string; text: string }
export interface Confirmation {
  code: string; name: string; candidateSource: Source; candidateTradeDate: string;
  candidateReason: string[]; sourceGeneratedAt: string; state: State; confirmationScore: number;
  chaseRisk: 'LOW' | 'MEDIUM' | 'HIGH'; reasons: Reason[]; stateReasons: Reason[];
  metrics: Record<string, number | string | boolean | null>;
  trend: Record<string, number | string | null>;
  firstConfirmedAt: string | null; failedAt: string | null; generatedAt: string | null;
  currentPriceRecovered: boolean;
}
export interface Snapshot {
  market: Market; tradeDate: string; candidateTradeDate: string | null; frozenAt: string | null;
  generatedAt: string | null; status: string; warnings: string[]; items: Confirmation[];
  summary: { total: number; wait: number; confirmed: number; failed: number }; rulesNote: string;
}
const base = '/api/v1/intraday-confirmation';
export const intradayConfirmationApi = {
  async read(market: Market, state?: State, source?: Source): Promise<Snapshot> {
    return toCamelCase((await apiClient.get(base, { params: { market, state, candidate_source: source } })).data);
  },
  async detail(code: string, market: Market): Promise<Confirmation> {
    return toCamelCase((await apiClient.get(`${base}/${encodeURIComponent(code)}`, { params: { market } })).data);
  },
  async run(market: Market): Promise<{ taskId: string }> {
    return toCamelCase((await apiClient.post(`${base}/run`, { market })).data);
  },
};
