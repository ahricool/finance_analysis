import { API_BASE_URL } from '@/utils/constants';
import type { MarketType } from './watchList';

export type RealtimeConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'unauthorized';

export type TrendDirection = 'above' | 'below' | 'neutral' | 'insufficient';

export type PatternType =
  | 'failed_breakout_reclaim'
  | 'breakout_retest_continuation'
  | 'micro_double_bottom_top'
  | 'impulse_pullback_resume'
  | 'compression_expansion'
  | 'vwap_reclaim_breakdown';

export type PatternDirection =
  | 'bullish_continuation'
  | 'bearish_continuation'
  | 'bearish_to_bullish'
  | 'bullish_to_bearish'
  | 'bullish_breakout'
  | 'bearish_breakout'
  | 'neutral_wait';

export type PatternStage = 'forming' | 'warning' | 'confirmed';
export type PatternStateStatus = 'insufficient' | 'none' | 'active';

export interface RealtimeTrend {
  timeframe: '1m';
  target_period: number;
  effective_period: number;
  minimum_period: number;
  state: TrendDirection;
  streak: number;
  ma_value?: number | null;
  close?: number | null;
  distance_pct?: number | null;
  bar_time?: string | null;
  trading_date?: string | null;
  trade_session?: string | null;
  confirmed: boolean;
}

export interface RealtimePatternSignal {
  timeframe: '1m';
  pattern_type: PatternType;
  pattern_name: string;
  direction: PatternDirection;
  stage: PatternStage;
  quality_score: number;
  occurred_at: string;
  confirmed_at?: string | null;
  trading_date?: string | null;
  trade_session?: string | null;
  bars_ago: number;
  session_minutes_ago: number;
  reference_level?: number | null;
  invalidation_price?: number | null;
  reasons: string[];
  confirmed: boolean;
}

export interface RealtimePatternState {
  timeframe: '1m';
  status: PatternStateStatus;
  trading_date?: string | null;
  bar_time?: string | null;
  signal?: RealtimePatternSignal | null;
}

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
  trend_1m?: RealtimeTrend | null;
  pattern_1m?: RealtimePatternState | null;
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
