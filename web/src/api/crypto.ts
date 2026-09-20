import apiClient from './index';
import { toCamelCase } from './utils';
import type { CryptoOverview, CryptoSnapshot } from '@/types/crypto';

export const cryptoApi = {
  async overview(): Promise<CryptoOverview> {
    return toCamelCase((await apiClient.get('/api/v1/crypto/btc/overview')).data);
  },
  async signals(): Promise<{ items: CryptoSnapshot[] }> {
    return toCamelCase((await apiClient.get('/api/v1/crypto/btc/signals')).data);
  },
};
