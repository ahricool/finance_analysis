import { beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { confluenceApi } from '../confluence';
import raw from '../../../e2e/fixtures/confluence';
vi.mock('../index', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
describe('confluence contract', () => {
  beforeEach(() => vi.clearAllMocks());
  it('preserves missing scores, independent dates and nested flow evidence', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: raw });
    const result = await confluenceApi.ranking({ market: 'CN', min_signals: 3 });
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/confluence/ranking', { params: { market: 'CN', min_signals: 3 } });
    expect(result.items[0]!.signals.etf.score).toBeNull();
    expect(result.items[0]!.signals.industry.tradeDate).toBe('2026-09-21');
    expect(result.items[0]!.signals.dragonTiger.evidence.hotMoneyNetInflow).toBeNull();
    expect(result.items[0]!.signals.industry.evidence.rankChange3D).toBe(8);
  });
});
