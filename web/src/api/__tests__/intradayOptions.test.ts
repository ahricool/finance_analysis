import { expect, it, vi } from 'vitest';
import apiClient from '../index';
import { fetchIntradayOptions } from '../intradayOptions';
vi.mock('../index', () => ({ default: { get: vi.fn() } }));
it('preserves nulls, signed directions, timestamps and score evidence', async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: { trading_date: '2026-11-12', generated_at: '2026-11-12T16:00:00Z',
    items: [{ symbol: 'SPCX.US', last_price: null, data_status: 'gap', result: { score: null, extension_atr: 2.5,
      windows: [{ minutes: 15, direction: -1, return_pct: -0.5, movement_gate: 0.6 }] } }] } });
  const signal = new AbortController().signal;
  const result = await fetchIntradayOptions(signal);
  expect(result.items[0]?.lastPrice).toBeNull();
  expect(result.items[0]?.result?.extensionAtr).toBe(2.5);
  expect(result.items[0]?.result?.windows[0]).toMatchObject({ direction: -1, returnPct: -0.5, movementGate: 0.6 });
  expect(apiClient.get).toHaveBeenCalledWith('/api/v1/intraday-options', { signal });
});
