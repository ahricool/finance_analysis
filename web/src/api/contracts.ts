import apiClient from './index';
import { API_BASE_URL } from '@/utils/constants';

export interface Contract { symbol: string; category: string }
export interface Quote {
  price: number; change_pct: number; turnover: number; funding_rate: number | null; timestamp: number;
}
export interface ContractQuote extends Contract { quote: Quote | null }
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
  async search(q: string): Promise<Contract[]> {
    return (await apiClient.get(path + '/search', { params: { q } })).data;
  },
  async add(contract: Contract): Promise<Contract> {
    return (await apiClient.post(path, contract)).data;
  },
  async remove(symbol: string): Promise<void> {
    await apiClient.delete(path + '/' + encodeURIComponent(symbol));
  },
  async bars(symbol: string): Promise<Candle[]> {
    return (await apiClient.get(path + '/' + encodeURIComponent(symbol) + '/bars', { params: { interval: '1d' } })).data;
  },
};

export function contractStreamUrl(transport: 'ws' | 'events', symbol: string, interval: '1d' | '1m'): string {
  const url = new URL(API_BASE_URL + path + '/' + transport, window.location.origin);
  if (symbol) url.searchParams.set('symbol', symbol);
  url.searchParams.set('interval', interval);
  if (transport === 'ws') url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}
