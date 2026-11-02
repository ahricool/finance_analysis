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
  it('passes the exact historical date and cancellation signal to detail reads', async () => {
    const signal = new AbortController().signal;
    vi.mocked(apiClient.get).mockResolvedValue({ data: { market: 'CN', trade_date: '2026-09-22', algorithm_version: 'confluence_v1', item: raw.items[0] } });
    const result = await confluenceApi.detail('600001.SH', 'CN', '2026-09-22', signal);
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/confluence/600001.SH', { params: { market: 'CN', trade_date: '2026-09-22' }, signal });
    expect(result.item.confluenceScore).toBe(88.24);
    expect(result.item.generatedAt).toBe('2026-09-22T12:30:00Z');
  });
});
