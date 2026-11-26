import type { TrendDirection, TrendStage, WindowScore, OpportunityBranch } from './intradayOptions';
import apiClient from './index';
import { API_BASE_URL } from '@/utils/constants';

export interface Contract { symbol: string; category: string; underlying_symbol: string | null }
export interface Quote {
  price: number; change_pct: number; turnover: number; funding_rate: number | null; timestamp: number;
}
export interface ContractQuote extends Contract { quote: Quote | null; analysis?: {
  score: number | null; direction: TrendDirection | null; state: TrendStage | null; reference: boolean; as_of: number;
  windows: Record<string, Pick<WindowScore, 'score' | 'direction' | 'returnPct' | 'dataStatus' | 'missingBars' | 'availableBars'>>;
  opportunity: Pick<OpportunityBranch, 'direction' | 'kind'> & {quality_score: number} | null;
} | null }
export interface Candle {
  timestamp: number; open: number; high: number; low: number; close: number; volume: number; turnover: number;
}
export interface MarketSnapshot {
  items: ContractQuote[]; symbol: string | null; minutes: Candle[] | null; daily_current: Candle | null;
}

const path = '/api/v1/crypto/contracts';
export const contractsApi = {
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
  async bars(symbol: string, signal?: AbortSignal): Promise<Candle[]> {
    return (await apiClient.get(path + '/' + encodeURIComponent(symbol) + '/bars', { params: { interval: '1d' }, signal })).data;
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
