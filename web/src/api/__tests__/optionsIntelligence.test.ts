import { describe, it, expect, vi } from 'vitest';
import apiClient from '../index';
import { optionsIntelligenceApi } from '../optionsIntelligence';
vi.mock('../index', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
describe('options API', () => {
  it('converts metric fields preserving missingness, OCC and timestamps', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { symbol: 'AAPL.US', latest: {
      scores: { bearish_demand: { value: null } }, iv_30d: .3,
      contracts: [{ symbol: 'AAPL261106P00100000', oi_date: null, quote_timestamp: '2026-10-07T18:00:00Z', feed_type: 'indicative' }],
    } } });
    const result = await optionsIntelligenceApi.detail('AAPL.US');
    expect(result.latest?.scores?.bearishDemand.value).toBeNull();
    expect(result.latest?.iv30D).toBe(.3);
    expect(result.latest?.contracts?.[0]).toMatchObject({ symbol: 'AAPL261106P00100000', oiDate: null,
      quoteTimestamp: '2026-10-07T18:00:00Z', feedType: 'indicative' });
  });
});
