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
  targetPeriod: number;
  effectivePeriod: number;
  minimumPeriod: number;
  state: TrendDirection;
  streak: number;
  maValue?: number | null;
  close?: number | null;
  distancePct?: number | null;
  barTime?: string | null;
  tradingDate?: string | null;
  tradeSession?: string | null;
  confirmed: boolean;
}

export interface RealtimePatternSignal {
  timeframe: '1m';
  patternType: PatternType;
  patternName: string;
  direction: PatternDirection;
  stage: PatternStage;
  qualityScore: number;
  occurredAt: string;
  confirmedAt?: string | null;
  tradingDate?: string | null;
  tradeSession?: string | null;
  barsAgo: number;
  sessionMinutesAgo: number;
  referenceLevel?: number | null;
  invalidationPrice?: number | null;
  reasons: string[];
  confirmed: boolean;
}

export interface RealtimePatternState {
  timeframe: '1m';
  status: PatternStateStatus;
  tradingDate?: string | null;
  barTime?: string | null;
  signal?: RealtimePatternSignal | null;
  previewStatus?: PatternStateStatus;
  previewSignal?: RealtimePatternSignal | null;
  previewBarTime?: string | null;
  previewPrice?: number | null;
  previewUpdatedAt?: string | null;
}

export interface RealtimeQuote {
  code: string;
  marketType: MarketType;
  symbol: string;
  available: boolean;
  source?: string;
  timestampKind?: string;
  sessionOpen?: string | null;
  sessionClose?: string | null;
  marketOpen?: boolean;
  quoteStatus?: 'current' | 'delayed' | 'unavailable';
  tradingDate?: string | null;
  lastPrice?: number | null;
  changeAmount?: number | null;
  changePct?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  preClose?: number | null;
  volume?: number | null;
  turnover?: number | null;
  tradeSession?: string | null;
  eventTime?: string | null;
  receivedAt?: string | null;
  trend1m?: RealtimeTrend | null;
  pattern1m?: RealtimePatternState | null;
}

export interface RealtimeQuoteMessage {
  type: 'quotes';
  generatedAt: string;
  quotes: RealtimeQuote[];
  portfolio: HoldingsSummary | null;
}

/** Backend wire quote: snake_case, with `_1m` keys that deep camelCase would turn into `1M`. */
export type RawRealtimeQuote = Record<string, unknown> & { trend_1m?: unknown; pattern_1m?: unknown };

export function toRealtimeQuote(raw: RawRealtimeQuote): RealtimeQuote {
  const { trend_1m: trend, pattern_1m: pattern, ...rest } = raw;
  return {
    ...toCamelCase<Omit<RealtimeQuote, 'trend1m' | 'pattern1m'>>(rest),
    trend1m: toCamelCase<RealtimeTrend | null | undefined>(trend),
    pattern1m: toCamelCase<RealtimePatternState | null | undefined>(pattern),
  };
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

function portfolioFromWire(value: unknown): HoldingsSummary | null {
  if (!value || typeof value !== 'object') return null;
  const portfolio = toCamelCase<HoldingsSummary>(value);
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
        let payload: unknown;
        try { payload = JSON.parse(data); } catch { continue; }
        const message = parseRealtimeQuoteMessage(payload);
        if (message) onMessage(message);
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

/** Validates a WS/SSE wire frame and converts it to the camelCase message shape. */
export function parseRealtimeQuoteMessage(value: unknown): RealtimeQuoteMessage | null {
  if (!value || typeof value !== 'object') return null;
  const message = value as { type?: unknown; generated_at?: unknown; quotes?: unknown; portfolio?: unknown };
  if (message.type !== 'quotes' || !Array.isArray(message.quotes)) return null;
  return {
    type: 'quotes',
    generatedAt: String(message.generated_at ?? ''),
    quotes: (message.quotes as RawRealtimeQuote[]).map(toRealtimeQuote),
    portfolio: portfolioFromWire(message.portfolio),
  };
}
