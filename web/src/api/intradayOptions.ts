import apiClient from './index';
import { toCamelCase } from './utils';

export type TrendDirection = 'bullish' | 'bearish' | 'neutral' | 'conflict';
export type TrendStage = 'continuing' | 'pullback' | 'extended' | 'conflict' | 'waiting';
export interface WindowScore {
  availableBars?: number | null; missingBars?: number | null;
  minutes: 5 | 15 | 30 | 60; dataStatus: 'ready' | 'warming' | 'gap'; score: number | null;
  direction: -1 | 0 | 1 | null; returnPct: number | null; startAt: string | null; endAt: string | null;
  stability: number | null; efficiency: number | null; strength: number | null; disturbance: number | null;
  normalizedMove: number | null; adverseMove: number | null; adverseDuration: number | null;
  movementGate: number | null; concentration: number | null; stalledImpulse: boolean; reasons: string[];
}
export interface IntradayStructure {
  kind: 'uptrend' | 'downtrend' | 'range' | 'breakout_up' | 'breakout_down' | 'failed_up' | 'failed_down' | 'rebound' | 'pullback' | 'unclear';
  phase: 'waiting' | 'forming' | 'confirmed' | 'retest' | 'failed' | 'continuing' | 'pullback' | 'pausing' | 'inside' | 'warming';
  background: 'bullish' | 'bearish' | 'neutral'; since: string; confirmedAt?: string | null; asOf: string;
  oversold: boolean; reference: boolean; availableBars: number; missingBars: number;
  box: { upper: number; lower: number; startAt: string; endAt: string; atr: number } | null;
  pivots: Array<{ kind: 'high' | 'low'; at: string; confirmedAt: string; price: number }>;
  reasons: string[];
}
export interface TrendResult {
  structure?: IntradayStructure | null;
  version: string; symbol: string; tradingDate: string; asOf: string; observedAt: string;
  windows: WindowScore[]; score: number | null; direction: TrendDirection | null; state: TrendStage | null;
  baseScore: number | null; alignment: number | null; extensionAtr: number | null; explanation: string;
}
export interface IntradayOptionRow {
  symbol: string; name: string | null; lastPrice: number | null; changePct: number | null; quoteTime: string | null;
  quoteStatus: 'missing' | 'ready' | 'delayed' | 'invalid_time';
  dataStatus: 'ready' | 'waiting' | 'warming' | 'gap' | 'delayed' | 'invalid_time';
  issues: string[]; result: TrendResult | null;
}
export interface IntradayOptionsSnapshot {
  tradingDate: string; marketStatus: 'open' | 'preopen' | 'closed'; generatedAt: string;
  version: string; items: IntradayOptionRow[];
}
export async function fetchIntradayOptions(signal: AbortSignal): Promise<IntradayOptionsSnapshot> {
  const { data } = await apiClient.get('/api/v1/intraday-options', { signal });
  return toCamelCase<IntradayOptionsSnapshot>(data);
}
