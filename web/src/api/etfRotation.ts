import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  ETFCandidatesResponse,
  ETFDatesResponse,
  ETFDetailResponse,
  ETFMarket,
  ETFRankingResponse,
  ETFRotationRunAccepted,
  ETFUniverseResponse,
} from '@/types/etfRotation';

export const etfRotationApi = {
  async ranking(market: ETFMarket = 'CN', tradeDate?: string): Promise<ETFRankingResponse> {
    const { data } = await apiClient.get('/api/v1/etf-rotation/ranking', {
      params: { market, ...(tradeDate ? { trade_date: tradeDate } : {}) },
    });
    return toCamelCase(data);
  },
  async candidates(market: ETFMarket = 'CN', tradeDate?: string): Promise<ETFCandidatesResponse> {
    const { data } = await apiClient.get('/api/v1/etf-rotation/candidates', {
      params: { market, ...(tradeDate ? { trade_date: tradeDate } : {}) },
    });
    return toCamelCase(data);
  },
  async dates(market: ETFMarket = 'CN'): Promise<ETFDatesResponse> {
    const { data } = await apiClient.get('/api/v1/etf-rotation/dates', { params: { market } });
    return toCamelCase(data);
  },
  async universe(market: ETFMarket = 'CN'): Promise<ETFUniverseResponse> {
    const { data } = await apiClient.get('/api/v1/etf-rotation/universe', { params: { market } });
    return toCamelCase(data);
  },
  async detail(code: string, market: ETFMarket = 'CN', limit = 60): Promise<ETFDetailResponse> {
    const { data } = await apiClient.get(`/api/v1/etf-rotation/${encodeURIComponent(code)}`, {
      params: { market, limit },
    });
    return toCamelCase(data);
  },
  async run(market: ETFMarket = 'CN', tradeDate?: string): Promise<ETFRotationRunAccepted> {
    const { data } = await apiClient.post('/api/v1/etf-rotation/run', {
      market,
      trade_date: tradeDate || null,
    });
    return toCamelCase(data);
  },
};
