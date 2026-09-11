import apiClient from './index';
import camelcaseKeys from 'camelcase-keys';
import { getParsedApiError } from './error';
import { toCamelCase } from './utils';
import type {
  TrendCandidatesResponse,
  TrendDatesResponse,
  TrendDetailResponse,
  TrendMarket,
  TrendPortfolioResponse,
  TrendPreviewResponse,
  TrendRankingResponse,
  TrendRunAccepted,
} from '@/types/trendFollowing';

// Walk only the DTO's known containers, never recurse through arbitrary snapshot JSON.
function rankingDto(data: Record<string, unknown>): TrendRankingResponse {
  const { items, changes, candidates, portfolio, ...summary } = data;
  const shallow = (value: unknown) => camelcaseKeys((value ?? {}) as Record<string, unknown>);
  const rows = (value: unknown) => (value as Record<string, unknown>[] ?? []).map(shallow);
  const mappedChanges = shallow(changes);
  for (const key of ['newCandidates', 'newWeakening', 'newReduces', 'newExits', 'transitions', 'movers']) {
    mappedChanges[key] = rows(mappedChanges[key]);
  }
  const mappedPortfolio = shallow(portfolio);
  mappedPortfolio.positions = rows(mappedPortfolio.positions);
  return {
    ...toCamelCase<TrendRankingResponse>(summary),
    items: (items as Record<string, unknown>[]).map(row => ({ ...shallow(row), features: shallow(row.features) })),
    changes: changes ? mappedChanges : null,
    candidates: rows(candidates),
    portfolio: mappedPortfolio,
  } as unknown as TrendRankingResponse;
}

export const trendFollowingApi = {
  async ranking(market: TrendMarket, tradeDate?: string): Promise<TrendRankingResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/ranking', {
      params: { market, ...(tradeDate ? { trade_date: tradeDate } : {}) },
    });
    return rankingDto(data);
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
  async preview(market: TrendMarket): Promise<TrendPreviewResponse | null> {
    try {
      const { data } = await apiClient.get('/api/v1/trend-following/preview', { params: { market } });
      return toCamelCase(data);
    } catch (error) {
      if (getParsedApiError(error).status === 404) return null;
      throw error;
    }
  },
};
