import { beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { trendFollowingApi } from '../trendFollowing';

vi.mock('../index', () => ({ default: { get: vi.fn(), post: vi.fn() } }));

describe('trendFollowingApi', () => {
  beforeEach(() => vi.clearAllMocks());

  it('converts nested snapshot fields and scopes ranking to market/date', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: {
      trade_date: '2026-08-28', market: 'US', items: [{ code: 'AAPL.US', alpha_score: 82,
        score_breakdown: { trend: { weighted_r2: 90 }, rs: { score: 57 }, setup: { volume_quality: 80 },
          path: { concentration_quality: 88 }, alpha: { version: 2, components: { trend: 80, rs: 70, setup: 60, path: 90 } } },
        features: { alpha_version: 2, path_score: 95, setup_score: 80,
          positive_return_concentration: .3, atr_expansion_ratio: 1.1, downside_control_quality: 90, return_5d: 0.03, return_10d: 0.06, return_20d: 0.1, weighted_r2: 0.9,
          rs_5d: 0.01, rs_10d: 0.02, trend_candidate: true, trend_resume: false } }],
      changes: {
        previous_trade_date: '2026-08-27',
        market_score_change: 2.5,
        breadth_score_change: 4,
        new_candidates: [],
        new_weakening: [],
        new_broken: [],
        transitions: [],
        movers: [{ current: { code: 'AAPL.US' }, previous_rank: 5, rank_change: 4,
          trend_score_change: 3, rs_score_change: 2, alpha_score_change: 2.5 }],
      },
    } });
    const result = await trendFollowingApi.ranking('US', '2026-08-28');
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/trend-following/ranking', {
      params: { market: 'US', trade_date: '2026-08-28' },
    });
    expect(result.items[0]).toMatchObject({ alphaScore: 82,
      features: {
      alphaVersion: 2, pathScore: 95, setupScore: 80, positiveReturnConcentration: .3,
      atrExpansionRatio: 1.1, downsideControlQuality: 90, return5D: 0.03, return10D: 0.06, return20D: 0.1, weightedR2: 0.9,
      rs5D: 0.01, rs10D: 0.02, trendCandidate: true, trendResume: false,
      r2Quality: 90, volumeQuality: 80, concentrationQuality: 88,
    } });
    expect(result.items[0]).not.toHaveProperty('scoreBreakdown');
    expect(result.changes).toMatchObject({
      previousTradeDate: '2026-08-27',
      marketScoreChange: 2.5,
      breadthScoreChange: 4,
      movers: [{ previousRank: 5, rankChange: 4, trendScoreChange: 3, rsScoreChange: 2 }],
    });
  });

  it('uses snapshot endpoints and submits asynchronous historical runs', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [] } });
    vi.mocked(apiClient.post).mockResolvedValue({ data: { task_id: 'task-1', status: 'pending', market: 'CN' } });
    await trendFollowingApi.dates('CN');
    await trendFollowingApi.candidates('CN', '2026-08-28');
    await trendFollowingApi.detail('000001.SZ', 'CN', 60, '2026-06-01');
    const result = await trendFollowingApi.run('CN', '2026-08-28');
    await trendFollowingApi.run('CN');
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/trend-following/dates', { params: { market: 'CN' } });
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/trend-following/candidates', {
      params: { market: 'CN', trade_date: '2026-08-28' },
    });

    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/trend-following/000001.SZ', {
      params: { market: 'CN', limit: 60, trade_date: '2026-06-01' },
    });
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/trend-following/run', {
      market: 'CN', trade_date: '2026-08-28',
    });
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/trend-following/run', {
      market: 'CN', trade_date: null,
    });
    expect(result.taskId).toBe('task-1');
  });


});

it('maps ranking snapshot rank changes including null and zero with the bounded DTO mapper', async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [
    { rank_change_1d: 5, rank_change_3d: -17, rank_change_5d: 32 },
    { rank_change_1d: 0, rank_change_3d: null, rank_change_5d: null },
  ] } });
  const items = (await trendFollowingApi.ranking('CN')).items;
  expect(items).toMatchObject([
    { rankChange1D: 5, rankChange3D: -17, rankChange5D: 32, features: {} },
    { rankChange1D: 0, rankChange3D: null, rankChange5D: null, features: {} },
  ]);
  expect(items[0]).not.toHaveProperty('scoreBreakdown');
  expect(items[1]).not.toHaveProperty('scoreBreakdown');
});

it('keeps null ranking scalars from the DTO instead of coercing them to zero or IDLE', async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [{
    code: 'NULL.US', rank: 4, alpha_score: 55,
    state: null, trend_score: null, rs_score: null, breakout_score: null,
    atr: null, reference_price: null,
  }] } });
  const item = (await trendFollowingApi.ranking('CN')).items[0]!;
  expect(item.state).toBeNull();
  expect(item.trendScore).toBeNull();
  expect(item.rsScore).toBeNull();
  expect(item.breakoutScore).toBeNull();
  expect(item.atr).toBeNull();
  expect(item.referencePrice).toBeNull();
  expect(item.alphaScore).toBe(55);
});

it('loads preview snapshots through toCamelCase and treats 404 as null', async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: {
    status: 'completed',
    trade_date: '2026-09-10',
    preview_time: '2026-09-10T03:00:00Z',
    data_as_of: '2026-09-10T14:34:59-04:00',
    provider: 'yfinance',
    snapshots: [{ code: 'AAPL.US', alpha_score: 82, market_regime: 'RISK_ON' }],
  } });
  const preview = await trendFollowingApi.preview('US');
  expect(apiClient.get).toHaveBeenCalledWith('/api/v1/trend-following/preview', { params: { market: 'US' } });
  expect(preview).toMatchObject({
    tradeDate: '2026-09-10',
    previewTime: '2026-09-10T03:00:00Z',
    dataAsOf: '2026-09-10T14:34:59-04:00',
    provider: 'yfinance',
    snapshots: [{ alphaScore: 82, marketRegime: 'RISK_ON' }],
  });
  vi.mocked(apiClient.get).mockRejectedValue({ parsedError: { status: 404, title: 'x', message: 'missing', rawMessage: 'missing', category: 'http_error' } });
  await expect(trendFollowingApi.preview('CN')).resolves.toBeNull();
});

it('loads lightweight preview status and preserves missing-cache null semantics', async () => {
  vi.mocked(apiClient.get).mockResolvedValueOnce({ data: {
    status: 'completed', market: 'CN', trade_date: '2026-09-11', preview_time: '2026-09-11T06:00:00Z',
    data_as_of: null, provider: 'yfinance', snapshot_count: 3794, warnings: [],
  } });
  const status = await trendFollowingApi.previewStatus('CN');
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/trend-following/preview/status', { params: { market: 'CN' } });
  expect(status).toMatchObject({ tradeDate: '2026-09-11', snapshotCount: 3794 });
  expect(status).not.toHaveProperty('snapshots');
  vi.mocked(apiClient.get).mockRejectedValueOnce({ response: { status: 404 } });
  await expect(trendFollowingApi.previewStatus('US')).resolves.toBeNull();
});

it('loads aggregated breadth with market, cutoff and preview mode', async () => {
  const counts = { IDLE: 10, WATCHING: 20, CANDIDATE: 10, TRENDING: 50, WEAKENING: 5, BROKEN: 5 };
  vi.mocked(apiClient.get).mockResolvedValue({ data: {
    market: 'US', dates: ['2026-09-11', '2026-09-14'], official_count: 1,
    preview_date: '2026-09-14', preview_time: null, generated_at: null, warnings: [],
    points: [{ trade_date: '2026-09-14', trend_breadth: 0.5, is_preview: true, state_counts: counts }],
  } });
  const result = await trendFollowingApi.breadthHistory('US', '2026-09-14', true);
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/trend-following/breadth-history', {
    params: { market: 'US', days: 30, as_of: '2026-09-14', include_preview: true },
  });
  expect(result).toMatchObject({ officialCount: 1, previewDate: '2026-09-14',
    points: [{ tradeDate: '2026-09-14', trendBreadth: 0.5, isPreview: true, stateCounts: counts }] });
  expect(result.points[0]!.stateCounts.TRENDING).toBe(50);
  expect(result.points[0]!.stateCounts).not.toHaveProperty('trending');
});
it('sends bounded transition filters and maps rank delta', async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [{ rank_delta: 9, is_preview: false }] } });
  const result = await trendFollowingApi.transitions('CN', 5, 'deteriorating', '2026-09-14', true);
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/trend-following/transitions', {
    params: { market: 'CN', days: 5, direction: 'deteriorating', limit: 20, as_of: '2026-09-14', include_preview: true },
  });
  expect(result.items[0]).toMatchObject({ rankDelta: 9, isPreview: false });
});
