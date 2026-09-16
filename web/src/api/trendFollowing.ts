import apiClient from './index';
import camelcaseKeys from 'camelcase-keys';
import { rankingSnapshotFromDto } from '@/utils/rankingFeatures';
import { getParsedApiError } from './error';
import { toCamelCase } from './utils';
import type {
  TrendCandidatesResponse,
  TrendDatesResponse,
  TrendDetailResponse,
  TrendMarket,
  TrendPreviewResponse,
  TrendPreviewStatusResponse,
  TrendRankingResponse,
  TrendRunAccepted,
  TrendBreadthResponse,
  TrendTransitionsResponse,
  TransitionDirection,
} from '@/types/trendFollowing';

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value);
}

// Walk only the DTO's known containers, never recurse through arbitrary snapshot JSON.
function rankingDto(data: Record<string, unknown>): TrendRankingResponse {
  const { items, changes, candidates, ...summary } = data;
  const shallow = (value: unknown) => camelcaseKeys((value ?? {}) as Record<string, unknown>);
  const rows = (value: unknown) => (value as Record<string, unknown>[] ?? []).map(shallow);
  const mappedChanges = shallow(changes);
  for (const key of ['newCandidates', 'newWeakening', 'newBroken', 'transitions', 'movers']) {
    mappedChanges[key] = rows(mappedChanges[key]);
  }
  return {
    ...toCamelCase<TrendRankingResponse>(summary),
    items: Array.isArray(items) ? items.filter(isRecord).map(rankingSnapshotFromDto) : [],
    changes: changes ? mappedChanges : null,
    candidates: rows(candidates),
  } as unknown as TrendRankingResponse;
}

export const trendFollowingApi = {
  async breadthHistory(market: TrendMarket, asOf?: string, includePreview = false): Promise<TrendBreadthResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/breadth-history', {
      params: { market, days: 30, include_preview: includePreview, ...(asOf ? { as_of: asOf } : {}) },
    });
    const result = toCamelCase<TrendBreadthResponse>(data);
    // State names are enum keys, not DTO field names.
    result.points.forEach((point, index) => { point.stateCounts = data.points[index].state_counts; });
    return result;
  },
  async transitions(market: TrendMarket, days: 1 | 3 | 5 = 3, direction: TransitionDirection = 'all',
    asOf?: string, includePreview = false): Promise<TrendTransitionsResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/transitions', {
      params: { market, days, direction, limit: 20, include_preview: includePreview, ...(asOf ? { as_of: asOf } : {}) },
    });
    return toCamelCase(data);
  },
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
  async dates(market: TrendMarket): Promise<TrendDatesResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/dates', { params: { market } });
    return toCamelCase(data);
  },
  async detailHistory(code: string, market: TrendMarket, beforeTradeDate: string, limit = 60): Promise<Pick<TrendDetailResponse, 'history'>> {
    const { data } = await apiClient.get(`/api/v1/trend-following/${encodeURIComponent(code)}`, {
      params: { market, limit, before_trade_date: beforeTradeDate },
    });
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
  async previewStatus(market: TrendMarket): Promise<TrendPreviewStatusResponse | null> {
    try {
      const { data } = await apiClient.get('/api/v1/trend-following/preview/status', { params: { market } });
      return toCamelCase(data);
    } catch (error) {
      if (getParsedApiError(error).status === 404) return null;
      throw error;
    }
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
