import type { TrendDirection, TrendStage, WindowScore, IntradayStructure, OpportunityBranch } from './intradayOptions';
import apiClient from './index';
import { API_BASE_URL } from '@/utils/constants';

export interface Contract { symbol: string; category: string; underlying_symbol: string | null }
export interface Quote {
  price: number; change_pct: number; turnover: number; funding_rate: number | null; funding_timestamp?: number | null; timestamp: number;
}
export interface RatioSample { source_time: number; long: number; short: number; ratio: number | null }
export interface MetricSample {
  timestamp: number;
  accounts: RatioSample | null; top_accounts: RatioSample | null; top_positions: RatioSample | null;
  oi: { quantity: number; usdt: number; source_time: number } | null;
  taker: { buy: number; sell: number; ratio: number | null; source_time: number } | null;
}
export interface HistorySample extends MetricSample {
  price: { open: number; close: number; source_time: number; source: string } | null;
  symbol: string; period: string;
}
export interface HourSummary extends MetricSample {
  price_change: number | null; oi_change: number | null; buy_share: number | null;
  status: Record<string, string>;
}
export interface Depth { timestamp: number; bids: number | null; asks: number | null; bids_levels: number; asks_levels: number }
export interface ContractQuote extends Contract {
  list_metrics?: Record<string, { value: number; timestamp: number; available_minutes?: number | null }> | null;
  metrics?: HourSummary | null;
  mark?: { timestamp: number; mark_price: number | null; index_price: number | null; basis: number | null;
    next_funding: number | null; funding_rate: number } | null;
  book?: { bid: number; ask: number; spread_bps: number; timestamp: number } | null;
  quote: Quote | null; analysis?: {
  trend_1m?: Record<string, unknown> | null; pattern_1m?: Record<string, unknown> | null;
  structure?: Pick<IntradayStructure, 'kind' | 'phase' | 'reference'> | null;
  score: number | null; direction: TrendDirection | null; state: TrendStage | null; reference: boolean; as_of: number;
  windows: Record<string, Pick<WindowScore, 'score' | 'direction' | 'returnPct' | 'dataStatus' | 'missingBars' | 'availableBars'>>;
  opportunity: Pick<OpportunityBranch, 'direction' | 'kind'> & {quality_score: number; confirmed_at?: string | null; expires_at?: string | null} | null;
} | null }
export type Candle = {
  closed?: boolean; received_at_ms?: number; event_time?: number;
  timestamp: number; open: number; high: number; low: number; close: number; volume: number; turnover: number;
}
export interface MarketSnapshot {
  items: ContractQuote[]; symbol: string | null; minutes: Candle[] | null; daily_current: Candle | null;
}

const path = '/api/v1/crypto/contracts';
export const contractsApi = {
  async favorites(): Promise<string[]> {
    return (await apiClient.get(path + '/favorites')).data;
  },
  async favorite(symbol: string, enabled: boolean): Promise<string[]> {
    return (await apiClient.put(path + '/' + encodeURIComponent(symbol) + '/favorite', { enabled })).data;
  },
  async snapshot(): Promise<MarketSnapshot> {
    return (await apiClient.get(path)).data;
  },
  async search(q: string, signal?: AbortSignal): Promise<Contract[]> {
    return (await apiClient.get(path + '/search', { params: { q }, signal })).data;
  },
  async add(contract: Pick<Contract, 'symbol' | 'category'>): Promise<Contract> {
    return (await apiClient.post(path, { symbol: contract.symbol, category: contract.category })).data;
  },
  async remove(symbol: string): Promise<void> {
    await apiClient.delete(path + '/' + encodeURIComponent(symbol));
  },
  async history(symbol: string, start: number, end: number, signal?: AbortSignal): Promise<HistorySample[]> {
    return (await apiClient.get(path + '/' + encodeURIComponent(symbol) + '/metrics', { params: { start, end, limit: 300 }, signal })).data.items;
  },
  async depth(symbol: string, signal?: AbortSignal): Promise<Depth | null> {
    return (await apiClient.get(path + '/' + encodeURIComponent(symbol) + '/depth', { signal })).data;
  },
  async bars(symbol: string, signal?: AbortSignal, interval: '1m' | '1d' = '1d', includeCurrent = false): Promise<Candle[]> {
    return (await apiClient.get(path + '/' + encodeURIComponent(symbol) + '/bars', { params: { interval, include_current: includeCurrent || undefined }, signal })).data;
  },
};

export function contractStreamUrl(transport: 'ws' | 'events', symbol: string, interval: '1d' | '1m'): string {
  const url = new URL(API_BASE_URL + path + '/' + transport, window.location.origin);
  if (symbol) url.searchParams.set('symbol', symbol);
  url.searchParams.set('interval', interval);
  url.searchParams.set('delta', 'true');
  if (transport === 'ws') url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}
