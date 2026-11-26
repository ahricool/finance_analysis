import apiClient from './index';
import { toRealtimeQuote, type RawRealtimeQuote, type RealtimeQuote, type RealtimePatternSignal } from './realtimeMarket';
import { toCamelCase } from './utils';

export type TradeSession = 'pre' | 'regular' | 'post' | 'overnight';

export interface IntradayBar {
  timestamp: number; open: number; high: number; low: number; close: number;
  volume: number; turnover: number | null; confirmed: boolean;
  sampled: boolean; sampleCount: number; partial: boolean;
  source?: string;
  tradeSession?: TradeSession;
}
export interface PatternEvent extends RealtimePatternSignal { observedAt: string }
export interface IntradaySnapshot {
  symbol: string; market: 'CN' | 'US'; tradingDate: string; generatedAt: string;
  reset: boolean; fullSnapshot?: boolean; historyVersion?: string | null; items: IntradayBar[]; quote: RealtimeQuote; events: PatternEvent[];
}
export async function fetchIntradayMarket(symbol: string, since: string | undefined, signal: AbortSignal, historyVersion?: string | null): Promise<IntradaySnapshot> {
  const { data } = await apiClient.get(`/api/v1/market-data/intraday/${encodeURIComponent(symbol)}`, { params: { since, history_version: since == null ? undefined : historyVersion }, signal });
  const { quote, ...rest } = data as Record<string, unknown> & { quote: RawRealtimeQuote };
  return { ...toCamelCase<Omit<IntradaySnapshot, 'quote'>>(rest), quote: quote && toRealtimeQuote(quote) };
}
