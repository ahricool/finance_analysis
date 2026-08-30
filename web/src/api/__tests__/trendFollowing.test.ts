import { beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { trendFollowingApi } from '../trendFollowing';

vi.mock('../index', () => ({ default: { get: vi.fn(), post: vi.fn() } }));

describe('trendFollowingApi', () => {
  beforeEach(() => vi.clearAllMocks());

  it('converts nested snapshot fields and scopes ranking to market/date', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: {
      trade_date: '2026-08-28', market: 'US', items: [{ code: 'AAPL.US', alpha_score: 82,
        features: { return_20d: 0.1, weighted_r2: 0.9 } }],
    } });
    const result = await trendFollowingApi.ranking('US', '2026-08-28');
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/trend-following/ranking', {
      params: { market: 'US', trade_date: '2026-08-28' },
    });
    expect(result.items[0]).toMatchObject({ alphaScore: 82, features: { return20D: 0.1, weightedR2: 0.9 } });
  });

  it('uses snapshot endpoints and submits asynchronous historical runs', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [] } });
    vi.mocked(apiClient.post).mockResolvedValue({ data: { task_id: 'task-1', status: 'pending', market: 'CN' } });
    await trendFollowingApi.dates('CN');
    await trendFollowingApi.candidates('CN', '2026-08-28');
    await trendFollowingApi.detail('000001.SZ', 'CN', 60);
    const result = await trendFollowingApi.run('CN', '2026-08-28');
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/trend-following/dates', { params: { market: 'CN' } });
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/trend-following/candidates', {
      params: { market: 'CN', trade_date: '2026-08-28' },
    });
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/trend-following/000001.SZ', { params: { market: 'CN', limit: 60 } });
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/trend-following/run', {
      market: 'CN', trade_date: '2026-08-28',
    });
    expect(result.taskId).toBe('task-1');
  });
});
