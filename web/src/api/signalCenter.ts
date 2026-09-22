import apiClient from './index';
import { toCamelCase } from './utils';

export type SignalMarket = 'CN' | 'US';
export interface SignalSummary {
  market: SignalMarket; signalDate: string; status: 'pending' | 'completed' | 'failed' | 'skipped';
  selectedSymbol: string | null; decision: 'BUY' | 'NO_TRADE' | null; confidence: string | null;
  createdAt: string; completedAt: string | null;
}
export interface SignalDetail extends SignalSummary {
  analysis: { thesis: string; positiveSignals: string[]; risks: string[]; invalidations: string[] } | null;
  candidateSnapshot: {
    capturedAt: string; candidates: Array<{ symbol: string }>;
    sourceAvailability: Record<string, { status: string; dataAsOf: string | null; generatedAt: string | null }>;
  };
  model: string | null; promptVersion: string; error: string | null;
}
export interface DailySignals { items: SignalDetail[]; requestedDates: Record<SignalMarket, string> }
const base = '/api/v1/signal-center';
export const signalCenterApi = {
  async daily(signalDate?: string): Promise<DailySignals> {
    const { data } = await apiClient.get(`${base}/daily`, { params: { signal_date: signalDate } });
    // Market identifiers are dictionary keys, not snake_case field names.
    return { items: toCamelCase(data.items), requestedDates: data.requested_dates };
  },
  async history(offset = 0): Promise<SignalSummary[]> {
    return toCamelCase((await apiClient.get(`${base}/history`, { params: { offset, limit: 50 } })).data);
  },
  async detail(market: SignalMarket, signalDate: string): Promise<SignalDetail> {
    return toCamelCase((await apiClient.get(`${base}/${market}/${signalDate}`)).data);
  },
};
