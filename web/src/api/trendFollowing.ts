import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  TrendCandidatesResponse,
  TrendDatesResponse,
  TrendDetailResponse,
  TrendMarket,
  TrendPortfolioResponse,
  TrendRankingResponse,
  TrendRunAccepted,
} from '@/types/trendFollowing';

export const trendFollowingApi = {
  async ranking(market: TrendMarket, tradeDate?: string): Promise<TrendRankingResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/ranking', {
      params: { market, ...(tradeDate ? { trade_date: tradeDate } : {}) },
    });
    return toCamelCase(data);
  },
  async candidates(market: TrendMarket, tradeDate?: string): Promise<TrendCandidatesResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/candidates', {
      params: { market, ...(tradeDate ? { trade_date: tradeDate } : {}) },
    });
    return toCamelCase(data);
  },
  async portfolio(market: TrendMarket, tradeDate?: string): Promise<TrendPortfolioResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/portfolio', {
      params: { market, ...(tradeDate ? { trade_date: tradeDate } : {}) },
    });
    return toCamelCase(data);
  },
  async dates(market: TrendMarket): Promise<TrendDatesResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/dates', { params: { market } });
    return toCamelCase(data);
  },
  async detail(code: string, market: TrendMarket, limit = 60, tradeDate?: string): Promise<TrendDetailResponse> {
    const { data } = await apiClient.get(`/api/v1/trend-following/${encodeURIComponent(code)}`, {
      params: { market, limit, ...(tradeDate ? { trade_date: tradeDate } : {}) },
    });
    return toCamelCase(data);
  },
  async run(market: TrendMarket, tradeDate?: string | null): Promise<TrendRunAccepted> {
    const { data } = await apiClient.post('/api/v1/trend-following/run', {
      market,
      trade_date: tradeDate ?? null,
    });
    return toCamelCase(data);
  },
};
