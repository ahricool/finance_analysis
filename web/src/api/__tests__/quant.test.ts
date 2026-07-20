import apiClient from '../index';
import { quantApi } from '../quant';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../index', () => ({
  default: {
    get: vi.fn(),
  },
}));

describe('quant API market scope', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        trade_date: null,
        market: 'CN',
        universe: 'cn_csi300_watchlist',
        market_regime: null,
        max_equity_exposure: null,
        items: [],
      },
    });
  });

  it('selects signal ranking by market without exposing a universe selector', async () => {
    await quantApi.signals('CN');

    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/quant/signals/ranking', {
      params: { market: 'CN' },
    });
  });
});
