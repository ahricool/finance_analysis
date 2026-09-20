import apiClient from './index';
import { toCamelCase } from './utils';
import type { CryptoOverview, CryptoSnapshot, CryptoPerformance, CryptoStrategyDefinition, CryptoPerformanceSummary } from '@/types/crypto';

export const cryptoApi = {
  async strategies(): Promise<CryptoStrategyDefinition[]> {
    return toCamelCase((await apiClient.get('/api/v1/crypto/btc/strategies')).data);
  },
  async summaries(): Promise<CryptoPerformanceSummary[]> {
    return toCamelCase((await apiClient.get('/api/v1/crypto/btc/strategies/performance')).data);
  },
  async performance(strategyKey: string): Promise<CryptoPerformance> {
    return toCamelCase((await apiClient.get(`/api/v1/crypto/btc/strategies/${encodeURIComponent(strategyKey)}/performance`)).data);
  },
  async overview(strategyKey?: string): Promise<CryptoOverview> {
    return toCamelCase((await apiClient.get(strategyKey ? `/api/v1/crypto/btc/strategies/${encodeURIComponent(strategyKey)}/overview` : '/api/v1/crypto/btc/overview')).data);
  },
  async signals(strategyKey: string, range?: { start: string; end: string }): Promise<{ items: CryptoSnapshot[] }> {
    return toCamelCase((await apiClient.get(`/api/v1/crypto/btc/strategies/${encodeURIComponent(strategyKey)}/signals`, range ? { params: { ...range, actions_only: true, limit: 2000 } } : undefined)).data);
  },
};
