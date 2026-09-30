import apiClient from './index';
import { toCamelCase } from './utils';

export interface DailyBar {
  tradeDate: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number | null;
}
export interface DailyBarsResponse {
  symbol: string;
  market: string;
  interval: '1d';
  adjustment: 'forward';
  source: string | null;
  historyFallback?: boolean;
  items: DailyBar[];
}
export interface ForwardReturnItem {
  code: string;
  forwardReturn3D: number | null;
  forwardReturn5D: number | null;
  forwardReturn10D: number | null;
  forwardReturn20D?: number | null;
}
export const marketDataApi = {
  async forwardReturns(symbols: string[], market: string, tradeDate: string, signal?: AbortSignal): Promise<{ items: ForwardReturnItem[] }> {
    return toCamelCase((await apiClient.post('/api/v1/market-data/forward-returns', {
      symbols, market, trade_date: tradeDate,
    }, { signal })).data);
  },
  async dailyBars(symbol: string, endDate?: string, startDate?: string, signal?: AbortSignal): Promise<DailyBarsResponse> {
    return toCamelCase((await apiClient.get(`/api/v1/market-data/daily-bars/${encodeURIComponent(symbol)}`, {
      params: { start_date: startDate, end_date: endDate }, signal,
    })).data);
  },
};
