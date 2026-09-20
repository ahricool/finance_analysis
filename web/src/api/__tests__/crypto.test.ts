import { expect, it, vi } from 'vitest';
import { cryptoApi } from '../crypto';
const get = vi.hoisted(() => vi.fn());
vi.mock('../index', () => ({ default: { get } }));
it('reads only backend strategy and preserves Decimal strings', async () => {
  get.mockResolvedValueOnce({ data: { symbol: 'BTCUSDT', strategy: { ema20_1h: '100.123456789012' }, state: { position_state: 'LONG' } } });
  expect((await cryptoApi.overview()).strategy?.ema201H).toBe('100.123456789012');
  expect(get).toHaveBeenLastCalledWith('/api/v1/crypto/btc/overview');
  get.mockResolvedValueOnce({ data: { items: [] } });
  expect(await cryptoApi.signals()).toEqual({ items: [] });
  expect(get).toHaveBeenLastCalledWith('/api/v1/crypto/btc/signals', undefined);
});
