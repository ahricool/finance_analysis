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
  changes: {
    previous_trade_date: '2026-08-22',
    new_buys: [{
      code: '588000.SH', name: '科创50ETF', current_state: 'EMERGING', current_action: 'BUY', current_rank: 3,
      previous_state: 'NEUTRAL',
      previous_action: null,
      previous_rank: 8,
      rank_change: 5,
      composite_score_change: 7.25,
    }],
    new_exits: [],
    new_emerging: [],
    new_cooling: [],
    regime_change: { from: 'NEUTRAL', to: 'RISK_ON' },
    rank_movers: [],
  },
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
      ret_3d: 0.018,
      ret_5d: 0.0234,
      ret_10d: -0.012,
      ret_20d: 0.04,
      rank_3d: 2,
      rank_5d: 3,
      rank_change_5d: 4,
      momentum_score: 80.1,
      entry_score: 88.2,
      reference_price: 100,
      realized_vol_20d: 0.3175,
      stop_loss_pct: 0.05,
      suggested_stop_price: 95,
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
    expect(ranking.changes).toMatchObject({
      previousTradeDate: '2026-08-22',
      regimeChange: { from: 'NEUTRAL', to: 'RISK_ON' },
      newBuys: [{ previousRank: 8, rankChange: 5, compositeScoreChange: 7.25 }],
    });
    expect(item).toMatchObject({
      ret1D: 0.011,
      ret3D: 0.018,
      ret5D: 0.0234,
      ret10D: -0.012,
      ret20D: 0.04,
      rank3D: 2,
      rank5D: 3,
      rankChange5D: 4,
      momentumScore: 80.1,
      entryScore: 88.2,
      referencePrice: 100,
      realizedVol20D: 0.3175,
      stopLossPct: 0.05,
      suggestedStopPrice: 95,
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

  it('loads preview payloads through toCamelCase and treats 404 as null', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        status: 'completed',
        trade_date: '2026-09-10',
        preview_time: '2026-09-10T06:35:06Z',
        data_as_of: '2026-09-10T06:34:57Z',
        provider: 'easyquotation_tencent',
        market_snapshot: { regime: 'RISK_ON' },
        items: [{ code: '588000.SH', is_candidate: true, composite_score: 81.3 }],
      },
    });
    const preview = await etfRotationApi.preview('CN');
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/etf-rotation/preview', { params: { market: 'CN' } });
    expect(preview).toMatchObject({
      tradeDate: '2026-09-10',
      previewTime: '2026-09-10T06:35:06Z',
      dataAsOf: '2026-09-10T06:34:57Z',
      provider: 'easyquotation_tencent',
      marketSnapshot: { regime: 'RISK_ON' },
      items: [{ isCandidate: true, compositeScore: 81.3 }],
    });

    vi.mocked(apiClient.get).mockRejectedValue({ parsedError: { status: 404, title: 'x', message: 'missing', rawMessage: 'missing', category: 'http_error' } });
    await expect(etfRotationApi.preview('US')).resolves.toBeNull();
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/etf-rotation/preview', { params: { market: 'US' } });
  });
});

it('passes the selected date to ETF detail', async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: {} });
  await etfRotationApi.detail('588000.SH', 'CN', 60, '2026-08-21');
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/etf-rotation/588000.SH', {
    params: { market: 'CN', limit: 60, trade_date: '2026-08-21' },
  });
});
