import apiClient from './index';
import { toCamelCase } from './utils';
import type { CryptoOverview, CryptoSnapshot, CryptoPerformance } from '@/types/crypto';

export const cryptoApi = {
  async performance(): Promise<CryptoPerformance> {
    return toCamelCase((await apiClient.get('/api/v1/crypto/btc/performance')).data);
  },
  async overview(): Promise<CryptoOverview> {
    return toCamelCase((await apiClient.get('/api/v1/crypto/btc/overview')).data);
  },
  async signals(range?: { start: string; end: string }): Promise<{ items: CryptoSnapshot[] }> {
    return toCamelCase((await apiClient.get('/api/v1/crypto/btc/signals', range ? { params: { ...range, actions_only: true } } : undefined)).data);
  },
};
