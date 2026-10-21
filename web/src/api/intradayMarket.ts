import apiClient from './index';
import type { RealtimeQuote, RealtimePatternSignal } from './realtimeMarket';

export interface IntradayBar {
  timestamp: number; open: number; high: number; low: number; close: number;
  volume: number; turnover: number | null; confirmed: boolean;
  sampled: boolean; sample_count: number; partial: boolean;
}
export interface PatternEvent extends RealtimePatternSignal { observed_at: string }
export interface IntradaySnapshot {
  symbol: string; market: 'CN' | 'US'; trading_date: string; generated_at: string;
  reset: boolean; items: IntradayBar[]; quote: RealtimeQuote; events: PatternEvent[];
}
export async function fetchIntradayMarket(symbol: string, since: string | undefined, signal: AbortSignal): Promise<IntradaySnapshot> {
  return (await apiClient.get(`/api/v1/market-data/intraday/${encodeURIComponent(symbol)}`, { params: { since }, signal })).data;
}
