import apiClient from './index';
import camelcaseKeys from 'camelcase-keys';
import { rankingSnapshotFromDto } from '@/utils/rankingFeatures';
import { getParsedApiError } from './error';
import { toCamelCase } from './utils';
import type {
  EventStudyResponse,
  EventStudySummaryResponse,
  EventStudyEventsResponse,
  StrategyKey,
  StudyRegime,
  TrendCandidatesResponse,
  TrendDashboardResponse,
  TrendDatesResponse,
  TrendDetailResponse,
  TrendMarket,
  TrendPeriod,
  TrendPreviewResponse,
  TrendPreviewRankingResponse,
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

interface TableDto {
  columns: string[];
  feature_columns: string[];
  rows: Array<Array<string | number | boolean | null>>;
}

function expandTable(table: TableDto): Record<string, unknown>[] {
  return table.rows.map(values => ({
    ...Object.fromEntries(table.columns.map((key, i) => [key, values[i]])),
    features: Object.fromEntries(table.feature_columns.map((key, i) => [key, values[table.columns.length + i]])),
  }));
}

export const trendFollowingApi = {
  async eventStudySummary(market: TrendMarket, startDate: string, endDate: string, regime: StudyRegime,
    signal?: AbortSignal, trendPeriod: TrendPeriod = 20): Promise<EventStudySummaryResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/event-study/summary', {
      params: { trend_period: trendPeriod, market, start_date: startDate, end_date: endDate, regime }, signal,
    });
    return toCamelCase(data);
  },
  async eventStudyEvents(market: TrendMarket, startDate: string, endDate: string, regime: StudyRegime,
    strategy: StrategyKey, offset = 0, signal?: AbortSignal, trendPeriod: TrendPeriod = 20): Promise<EventStudyEventsResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/event-study/events', {
      params: { trend_period: trendPeriod, market, start_date: startDate, end_date: endDate, regime, strategy, offset, limit: 100 }, signal,
    });
    return toCamelCase(data);
  },
  async eventStudy(market: TrendMarket, startDate: string, endDate: string, regime: StudyRegime,
    strategy: StrategyKey | 'ALL' = 'ALL', offset = 0, signal?: AbortSignal, trendPeriod: TrendPeriod = 20): Promise<EventStudyResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/event-study', {
      params: { trend_period: trendPeriod, market, start_date: startDate, end_date: endDate, regime, strategy, offset, limit: 100 }, signal,
    });
    return toCamelCase(data);
  },
  async dashboard(market: TrendMarket, trendPeriod: TrendPeriod = 20): Promise<TrendDashboardResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/dashboard', { params: { trend_period: trendPeriod, market } });
    const result = toCamelCase<TrendDashboardResponse>(data);
    result.changes.stateCounts = data.changes.state_counts;
    return result;
  },
  async breadthHistory(market: TrendMarket, asOf?: string, includePreview = false, trendPeriod: TrendPeriod = 20): Promise<TrendBreadthResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/breadth-history', {
      params: { trend_period: trendPeriod, market, days: 30, include_preview: includePreview, ...(asOf ? { as_of: asOf } : {}) },
    });
    const result = toCamelCase<TrendBreadthResponse>(data);
    // State names are enum keys, not DTO field names.
    result.points.forEach((point, index) => { point.stateCounts = data.points[index].state_counts; });
    return result;
  },
  async transitions(market: TrendMarket, days: 1 | 3 | 5 = 3, direction: TransitionDirection = 'all',
    asOf?: string, includePreview = false, trendPeriod: TrendPeriod = 20): Promise<TrendTransitionsResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/transitions', {
      params: { trend_period: trendPeriod, market, days, direction, limit: 20, include_preview: includePreview, ...(asOf ? { as_of: asOf } : {}) },
    });
    return toCamelCase(data);
  },
  async ranking(market: TrendMarket, tradeDate?: string, trendPeriod: TrendPeriod = 20): Promise<TrendRankingResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/ranking/table', {
      params: { trend_period: trendPeriod, market, ...(tradeDate ? { trade_date: tradeDate } : {}) },
    });
    const { table, ...summary } = data;
    return rankingDto({ ...summary, items: expandTable(table) });
  },
  async snapshotStatus(market: TrendMarket, trendPeriod: TrendPeriod = 20): Promise<{ tradeDate: string; generatedAt: string | null } | null> {
    try {
      const { data } = await apiClient.get('/api/v1/trend-following/status', { params: { market, trend_period: trendPeriod } });
      return toCamelCase(data);
    } catch (error) {
      if (getParsedApiError(error).status === 404) return null;
      throw error;
    }
  },
  async previewDetail(code: string, market: TrendMarket, tradeDate?: string, trendPeriod: TrendPeriod = 20,
    signal?: AbortSignal): Promise<TrendDetailResponse> {
    const { data } = await apiClient.get(`/api/v1/trend-following/preview/stocks/${encodeURIComponent(code)}`, {
      params: { market, trend_period: trendPeriod, ...(tradeDate ? { trade_date: tradeDate } : {}) }, signal,
    });
    return toCamelCase(data);
  },
  async previewRanking(market: TrendMarket, trendPeriod: TrendPeriod = 20): Promise<TrendPreviewRankingResponse | null> {
    try {
      const { data } = await apiClient.get('/api/v1/trend-following/preview/ranking', { params: { market, trend_period: trendPeriod } });
      const { table, ...summary } = data;
      return { ...toCamelCase<TrendPreviewRankingResponse>(summary), snapshots: expandTable(table).map(rankingSnapshotFromDto) };
    } catch (error) {
      if (getParsedApiError(error).status === 404) return null;
      throw error;
    }
  },
  async candidates(market: TrendMarket, tradeDate?: string, trendPeriod: TrendPeriod = 20): Promise<TrendCandidatesResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/candidates', {
      params: { trend_period: trendPeriod, market, ...(tradeDate ? { trade_date: tradeDate } : {}) },
    });
    return toCamelCase(data);
  },
  async dates(market: TrendMarket, trendPeriod: TrendPeriod = 20): Promise<TrendDatesResponse> {
    const { data } = await apiClient.get('/api/v1/trend-following/dates', { params: { trend_period: trendPeriod, market } });
    return toCamelCase(data);
  },
  async detailHistory(code: string, market: TrendMarket, beforeTradeDate: string, limit = 60, trendPeriod: TrendPeriod = 20): Promise<Pick<TrendDetailResponse, 'history'>> {
    const { data } = await apiClient.get(`/api/v1/trend-following/${encodeURIComponent(code)}`, {
      params: { trend_period: trendPeriod, market, limit, before_trade_date: beforeTradeDate },
    });
    return toCamelCase(data);
  },
  async detail(code: string, market: TrendMarket, limit = 60, tradeDate?: string, trendPeriod: TrendPeriod = 20): Promise<TrendDetailResponse> {
    const { data } = await apiClient.get(`/api/v1/trend-following/${encodeURIComponent(code)}`, {
      params: { trend_period: trendPeriod, market, limit, ...(tradeDate ? { trade_date: tradeDate } : {}) },
    });
    return toCamelCase(data);
  },
  async run(market: TrendMarket, tradeDate?: string | null, trendPeriod: TrendPeriod = 20): Promise<TrendRunAccepted> {
    const { data } = await apiClient.post('/api/v1/trend-following/run', {
      market,
      trade_date: tradeDate ?? null,
      trend_period: trendPeriod,
    });
    return toCamelCase(data);
  },
  async previewStatus(market: TrendMarket, trendPeriod: TrendPeriod = 20): Promise<TrendPreviewStatusResponse | null> {
    try {
      const { data } = await apiClient.get('/api/v1/trend-following/preview/status', { params: { trend_period: trendPeriod, market } });
      return toCamelCase(data);
    } catch (error) {
      if (getParsedApiError(error).status === 404) return null;
      throw error;
    }
  },
  async preview(market: TrendMarket, trendPeriod: TrendPeriod = 20): Promise<TrendPreviewResponse | null> {
    try {
      const { data } = await apiClient.get('/api/v1/trend-following/preview', { params: { trend_period: trendPeriod, market } });
      return toCamelCase(data);
    } catch (error) {
      if (getParsedApiError(error).status === 404) return null;
      throw error;
    }
  },
};
