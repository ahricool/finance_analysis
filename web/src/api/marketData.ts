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
  items: DailyBar[];
}
export const marketDataApi = {
  async dailyBars(symbol: string, endDate?: string, startDate?: string, signal?: AbortSignal): Promise<DailyBarsResponse> {
    return toCamelCase((await apiClient.get(`/api/v1/market-data/daily-bars/${encodeURIComponent(symbol)}`, {
      params: { start_date: startDate, end_date: endDate }, signal,
    })).data);
  },
};
