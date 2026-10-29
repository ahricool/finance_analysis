import { beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { stocksApi } from '../stocks';

vi.mock('../index', () => ({ default: { get: vi.fn() } }));

describe('stock classification', () => {
  beforeEach(() => vi.resetAllMocks());

  it('normalizes industry observation dates and passes cancellation to the read-only endpoint', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: {
      code: '600519.SH', market: 'CN', etf_proxies: [{ code: '512690.SH', name: '酒ETF', reasons: ['白酒代理'] }], etf_proxy_unavailable_reasons: [], memberships: { indices: [], industries: [
        { code: '881101.TI', name: '食品饮料', members_observed_at: '2026-10-11T02:00:00Z' },
      ] },
    } });
    const controller = new AbortController();
    const result = await stocksApi.classification('600519.SH', controller.signal);
    expect(result.etfProxies).toEqual([{ code: '512690.SH', name: '酒ETF', reasons: ['白酒代理'] }]);
    expect(result.etfProxyUnavailableReasons).toEqual([]);
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/stocks/600519.SH/classification', { signal: expect.any(AbortSignal) });
    expect(result.memberships.industries?.[0]).toEqual({
      code: '881101.TI', name: '食品饮料', membersObservedAt: '2026-10-11T02:00:00Z',
    });
  });

  it('shares a pending request without one consumer cancelling another and reuses the resolved response', async () => {
    let finish!: (value: { data: object }) => void;
    vi.mocked(apiClient.get).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const first = new AbortController();
    const second = new AbortController();
    const firstRead = stocksApi.classification('600001.SH', first.signal);
    const firstResult = expect(firstRead).rejects.toMatchObject({ name: 'AbortError' });
    const secondRead = stocksApi.classification('600001.SH', second.signal);
    const sharedSignal = vi.mocked(apiClient.get).mock.calls[0]![1]!.signal!;
    first.abort();
    await firstResult;
    expect(sharedSignal.aborted).toBe(false);
    finish({ data: { code: '600001.SH', market: 'CN', memberships: { indices: [], industries: [] } } });
    const data = await secondRead;
    data.market = 'MUTATED';
    expect((await stocksApi.classification('600001.SH')).market).toBe('CN');
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it('cancels the underlying request after the last subscriber leaves and retries failures', async () => {
    vi.mocked(apiClient.get).mockImplementationOnce(() => new Promise(() => {}));
    const controller = new AbortController();
    const pending = stocksApi.classification('600002.SH', controller.signal);
    const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    const signal = vi.mocked(apiClient.get).mock.calls[0]![1]!.signal!;
    controller.abort(); await rejected;
    expect(signal.aborted).toBe(true);
    vi.mocked(apiClient.get).mockRejectedValueOnce(new Error('offline'));
    await expect(stocksApi.classification('600002.SH')).rejects.toThrow('offline');
    vi.mocked(apiClient.get).mockResolvedValue({ data: { code: '600002.SH', market: 'CN', memberships: { indices: [] } } });
    expect((await stocksApi.classification('600002.SH')).code).toBe('600002.SH');
    expect(apiClient.get).toHaveBeenCalledTimes(3);
  });

  it('refreshes successful metadata after the short reuse window', async () => {
    const clock = vi.spyOn(Date, 'now').mockReturnValue(200_000);
    vi.mocked(apiClient.get).mockResolvedValue({ data: { code: '600003.SH', market: 'CN', memberships: { indices: [] } } });
    try {
      await stocksApi.classification('600003.SH');
      await stocksApi.classification('600003.SH');
      expect(apiClient.get).toHaveBeenCalledTimes(1);
      clock.mockReturnValue(260_001);
      await stocksApi.classification('600003.SH');
      expect(apiClient.get).toHaveBeenCalledTimes(2);
    } finally {
      clock.mockRestore();
    }
  });
});
