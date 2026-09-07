import apiClient from './index';
import { toCamelCase } from './utils';
import { API_BASE_URL } from '@/utils/constants';
import type { CryptoKline, CryptoOverview, CryptoSnapshot, CryptoStatus } from '@/types/crypto';

export const cryptoApi = {
  async overview(): Promise<CryptoOverview> {
    return toCamelCase((await apiClient.get('/api/v1/crypto/btc/overview')).data);
  },
  async klines(limit = 1000): Promise<{ items: CryptoKline[] }> {
    return toCamelCase((await apiClient.get('/api/v1/crypto/btc/klines', { params: { interval: '1m', limit } })).data);
  },
  async signals(): Promise<{ items: CryptoSnapshot[] }> {
    return toCamelCase((await apiClient.get('/api/v1/crypto/btc/signals')).data);
  },
  async status(): Promise<CryptoStatus> {
    return toCamelCase((await apiClient.get('/api/v1/crypto/btc/status')).data);
  },
};

export function cryptoWebSocketUrl() {
  const url = new URL('/api/v1/crypto/ws', API_BASE_URL || window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

export function parseCryptoMessage(raw: string): CryptoStatus | null {
  const data = JSON.parse(raw);
  if (data?.type !== 'state' || data?.market?.symbol !== 'BTCUSDT') return null;
  if (!['websocket', 'http_fallback'].includes(data.market.stream_mode)) return null;
  return toCamelCase(data.market);
}
