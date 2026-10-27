import { API_BASE_URL } from '@/utils/constants';
import type { MarketType } from './watchList';
import type { HoldingsSummary } from './holdings';
import { toCamelCase } from './utils';

export type RealtimeConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'unauthorized' | 'sse' | 'sse-reconnecting' | 'paused';
export interface MarketStreamOptions {
  scope?: 'watch-list' | 'holdings'; market?: 'CN' | 'US'; tagId?: number; ungrouped?: boolean;
}

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
  preview_status?: PatternStateStatus;
  preview_signal?: RealtimePatternSignal | null;
  preview_bar_time?: string | null;
  preview_price?: number | null;
  preview_updated_at?: string | null;
}

export interface RealtimeQuote {
  code: string;
  market_type: MarketType;
  symbol: string;
  available: boolean;
  source?: string;
  timestamp_kind?: string;
  session_open?: string | null;
  session_close?: string | null;
  market_open?: boolean;
  quote_status?: 'current' | 'delayed' | 'unavailable';
  trading_date?: string | null;
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
  portfolio?: unknown;
}

export function marketQuoteKey(code: string, marketType: MarketType): string {
  return `${marketType}:${code.trim().toUpperCase()}`;
}

function marketUrl(path: string, options: MarketStreamOptions): URL {
  const base = API_BASE_URL || window.location.origin;
  const url = new URL(base, window.location.origin);
  url.pathname = `${url.pathname.replace(/\/$/, '')}/api/v1/market-data/${path}`.replace(/\/+/g, '/');
  url.search = '';
  url.hash = '';
  if (options.scope) url.searchParams.set('scope', options.scope);
  if (options.market) url.searchParams.set('market', options.market);
  if (options.tagId !== undefined) url.searchParams.set('tag_id', String(options.tagId));
  if (options.ungrouped) url.searchParams.set('ungrouped', 'true');
  return url;
}

export function buildMarketWebSocketUrl(options: MarketStreamOptions = {}): string {
  const url = marketUrl('ws', options);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

export class MarketStreamAuthError extends Error {
  constructor(readonly status: number) { super(`Market stream rejected with ${status}`); }
}

export function portfolioFromMessage(message: RealtimeQuoteMessage): HoldingsSummary | null {
  if (!message.portfolio || typeof message.portfolio !== 'object') return null;
  const portfolio = toCamelCase<HoldingsSummary>(message.portfolio);
  return Array.isArray(portfolio.positions) && Array.isArray(portfolio.accounts) ? portfolio : null;
}

export async function readMarketEvents(
  options: MarketStreamOptions, signal: AbortSignal, onMessage: (message: RealtimeQuoteMessage) => void,
  onActivity: () => void = () => {},
): Promise<void> {
  const response = await fetch(marketUrl('events', options), {
    credentials: 'include', headers: { Accept: 'text/event-stream' }, signal,
  });
  if (response.status === 401 || response.status === 403) throw new MarketStreamAuthError(response.status);
  if (!response.ok || !response.body) throw new Error('行情连接失败');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    onActivity(); // HTTP is connected even when the first quote is still being collected.
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) throw new Error('行情连接已断开');
      if (value.byteLength) onActivity(); // Includes comment heartbeats and fragmented frames.
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() || '';
      for (const frame of frames) {
        const data = frame.split(/\r?\n/).filter(line => line.startsWith('data:'))
          .map(line => line.slice(5).trimStart()).join('\n');
        if (!data) continue;
        let message: unknown;
        try { message = JSON.parse(data); } catch { continue; }
        if (isRealtimeQuoteMessage(message)) onMessage(message);
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function isRealtimeQuoteMessage(value: unknown): value is RealtimeQuoteMessage {
  if (!value || typeof value !== 'object') return false;
  const message = value as Partial<RealtimeQuoteMessage>;
  return message.type === 'quotes' && Array.isArray(message.quotes);
}
