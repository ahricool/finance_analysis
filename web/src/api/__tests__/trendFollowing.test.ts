import { beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { trendFollowingApi } from '../trendFollowing';

vi.mock('../index', () => ({ default: { get: vi.fn(), post: vi.fn() } }));

describe('trendFollowingApi', () => {
  beforeEach(() => vi.clearAllMocks());

  it('converts nested snapshot fields and scopes ranking to market/date', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: {
      trade_date: '2026-08-28', market: 'US', items: [{ code: 'AAPL.US', alpha_score: 82,
        features: { return_5d: 0.03, return_10d: 0.06, return_20d: 0.1, weighted_r2: 0.9,
          rs_5d: 0.01, rs_10d: 0.02, breakout_10d: true, trend_resume: false } }],
      changes: {
        previous_trade_date: '2026-08-27',
        market_score_change: 2.5,
        breadth_score_change: 4,
        new_candidates: [],
        new_weakening: [],
        new_reduces: [],
        new_exits: [],
        transitions: [],
        movers: [{ current: { code: 'AAPL.US' }, previous_rank: 5, rank_change: 4,
          trend_score_change: 3, rs_score_change: 2, alpha_score_change: 2.5 }],
      },
    } });
    const result = await trendFollowingApi.ranking('US', '2026-08-28');
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/trend-following/ranking', {
      params: { market: 'US', trade_date: '2026-08-28' },
    });
    expect(result.items[0]).toMatchObject({ alphaScore: 82, features: {
      return5D: 0.03, return10D: 0.06, return20D: 0.1, weightedR2: 0.9,
      rs5D: 0.01, rs10D: 0.02, breakout10D: true, trendResume: false,
    } });
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
