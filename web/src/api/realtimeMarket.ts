import { API_BASE_URL } from '@/utils/constants';
import type { MarketType } from './watchList';

export type RealtimeConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'unauthorized';

export interface RealtimeQuote {
  code: string;
  market_type: MarketType;
  symbol: string;
  available: boolean;
  last_price?: number | null;
  change_amount?: number | null;
  change_pct?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  pre_close?: number | null;
  volume?: number | null;
  turnover?: number | null;
  trade_session?: string | null;
  event_time?: string | null;
  received_at?: string | null;
}

export interface RealtimeQuoteMessage {
  type: 'quotes';
  generated_at: string;
  quotes: RealtimeQuote[];
}

export function marketQuoteKey(code: string, marketType: MarketType): string {
  return `${marketType}:${code.trim().toUpperCase()}`;
}

export function buildMarketWebSocketUrl(): string {
  const base = API_BASE_URL || window.location.origin;
  const url = new URL(base, window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = `${url.pathname.replace(/\/$/, '')}/api/v1/market-data/ws`.replace(/\/+/g, '/');
  url.search = '';
  url.hash = '';
  return url.toString();
}

export function isRealtimeQuoteMessage(value: unknown): value is RealtimeQuoteMessage {
  if (!value || typeof value !== 'object') return false;
  const message = value as Partial<RealtimeQuoteMessage>;
  return message.type === 'quotes' && Array.isArray(message.quotes);
}
