import apiClient from '../index';
import { etfRotationApi } from '../etfRotation';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../index', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

const rankingPayload = {
  trade_date: '2026-08-25',
  universe_size: 40,
  data_ready_count: 40,
  data_coverage: 1,
  rankable_size: 40,
  rankable_coverage: 1,
  generated_at: '2026-08-25T10:40:00+00:00',
  warnings: [],
  items: [
    {
      id: 1,
      trade_date: '2026-08-25',
      code: '588000.SH',
      name: '科创50ETF',
      category: 'BROAD_INDEX',
      theme: 'STAR50',
      risk_group: 'BROAD_GROWTH',
      enabled: true,
      ret_1d: 0.011,
      ret_5d: 0.0234,
      ret_10d: -0.012,
      ret_20d: 0.04,
      ret_30d: 0.05,
      ret_60d: 0.0611,
      rank_5d: 3,
      rank_change_5d: 4,
      momentum_score: 80.1,
      entry_score: 88.2,
      state: 'TRENDING',
      overheated: false,
      candidate_rank: 1,
      is_candidate: true,
      score_components: { base_momentum: 70 },
      generated_at: '2026-08-25T10:40:00+00:00',
    },
  ],
};

describe('etfRotation API key conversion', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ data: rankingPayload });
  });

  it('maps ret_Nd snapshot fields to camelcase-keys digit-letter keys', async () => {
    const ranking = await etfRotationApi.ranking();
    const [item] = ranking.items;

    expect(ranking.tradeDate).toBe('2026-08-25');
    expect(item).toMatchObject({
      ret1D: 0.011,
      ret5D: 0.0234,
      ret10D: -0.012,
      ret20D: 0.04,
      ret30D: 0.05,
      ret60D: 0.0611,
      rank5D: 3,
      rankChange5D: 4,
      momentumScore: 80.1,
      entryScore: 88.2,
    });
    expect(item).not.toHaveProperty('ret5d');
    expect(item).not.toHaveProperty('rank5d');
  });

  it('scopes dates, ranking and candidates to the requested market', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { market: 'US', latest: '2026-08-20', items: ['2026-08-20'] },
    });
    await etfRotationApi.dates('US');
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/etf-rotation/dates', { params: { market: 'US' } });

    vi.mocked(apiClient.get).mockResolvedValue({ data: rankingPayload });
    await etfRotationApi.ranking('US', '2026-08-20');
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/etf-rotation/ranking', {
      params: { market: 'US', trade_date: '2026-08-20' },
    });
    await etfRotationApi.candidates('US', '2026-08-20');
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/etf-rotation/candidates', {
      params: { market: 'US', trade_date: '2026-08-20' },
    });
  });
});
