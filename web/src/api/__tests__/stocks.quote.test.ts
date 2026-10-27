import { beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { stocksApi } from '../stocks';
vi.mock('../index', () => ({ default: { get: vi.fn() } }));
beforeEach(() => vi.resetAllMocks());
describe('stocksApi.quote', () => {
  it('adapts the existing stock quote response without fabricating absent timestamps or prices', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { stock_code: 'AAPL.US', current_price: 123.45, change: null, change_percent: null, prev_close: 122, amount: null, update_time: null } });
    const controller = new AbortController();
    const quote = await stocksApi.quote('AAPL.US', 'US', controller.signal);
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/stocks/AAPL.US/quote', { signal: controller.signal });
    expect(quote).toMatchObject({ code: 'AAPL.US', symbol: 'AAPL.US', marketType: 'US', available: true, lastPrice: 123.45, changeAmount: null, changePct: null, preClose: 122, turnover: null, eventTime: null });
    expect(quote.receivedAt).toBeUndefined();
  });
  it('does not present a missing/default-zero upstream price as an available quote', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { stock_code: 'AAPL.US', current_price: 0 } });
    expect((await stocksApi.quote('AAPL.US', 'US')).available).toBe(false);
  });
});
