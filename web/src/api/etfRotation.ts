import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  ETFCandidatesResponse,
  ETFDetailResponse,
  ETFRankingResponse,
  ETFRotationRunAccepted,
} from '@/types/etfRotation';

export const etfRotationApi = {
  async ranking(tradeDate?: string): Promise<ETFRankingResponse> {
    const { data } = await apiClient.get('/api/v1/etf-rotation/ranking', {
      params: tradeDate ? { trade_date: tradeDate } : {},
    });
    return toCamelCase(data);
  },
  async candidates(tradeDate?: string): Promise<ETFCandidatesResponse> {
    const { data } = await apiClient.get('/api/v1/etf-rotation/candidates', {
      params: tradeDate ? { trade_date: tradeDate } : {},
    });
    return toCamelCase(data);
  },
  async detail(code: string, limit = 60): Promise<ETFDetailResponse> {
    const { data } = await apiClient.get(`/api/v1/etf-rotation/${encodeURIComponent(code)}`, {
      params: { limit },
    });
    return toCamelCase(data);
  },
  async run(tradeDate?: string): Promise<ETFRotationRunAccepted> {
    const { data } = await apiClient.post('/api/v1/etf-rotation/run', {
      trade_date: tradeDate || null,
    });
    return toCamelCase(data);
  },
};
