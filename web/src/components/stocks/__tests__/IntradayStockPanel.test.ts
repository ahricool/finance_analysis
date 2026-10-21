import { mount, flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import IntradayStockPanel from '../IntradayStockPanel.vue';
import type { IntradaySnapshot } from '@/api/intradayMarket';

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock('@/api/intradayMarket', () => ({ fetchIntradayMarket: mocks.fetch }));
vi.mock('@/components/market-data/tradeMarkerOverlay', () => ({ ensureTradeMarkerOverlay: () => {} }));
const at = Date.parse('2026-10-21T15:00:00Z');
function snapshot(symbol = 'AAPL.US', timestamp = at, price = 100): IntradaySnapshot {
  return { symbol, market: 'US', trading_date: '2026-10-21', generated_at: new Date(at).toISOString(), reset: true,
    items: [{ timestamp, open: price, high: price + 1, low: price - 1, close: price, volume: 10,
      turnover: null, confirmed: false, sampled: false, sample_count: 0, partial: false }],
    quote: { code: symbol, symbol, market_type: 'US', available: true, last_price: price }, events: [] };
}
function mountPanel() {
  return mount(IntradayStockPanel, { props: { symbol: 'AAPL.US', market: 'US' }, global: { stubs: { MarketKLineChart: true } } });
}
beforeEach(() => { vi.useFakeTimers(); mocks.fetch.mockReset(); });
afterEach(() => { vi.useRealTimers(); });

describe('inline intraday ownership and incremental updates', () => {
  it('loads only while mounted and merges the closing current minute', async () => {
    const initial = snapshot();
    const next = snapshot('AAPL.US', at + 60_000, 101);
    next.reset = false;
    next.items.unshift({ ...initial.items[0]!, confirmed: true });
    mocks.fetch.mockResolvedValueOnce(initial).mockResolvedValue(next);
    const panel = mountPanel();
    await flushPromises();
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5_000);
    await flushPromises();
    expect(mocks.fetch.mock.calls[1]?.[1]).toBe(new Date(at).toISOString());
    expect(panel.text()).toContain('已采集 2 根');
    const signal = mocks.fetch.mock.calls[1]?.[2] as AbortSignal;
    panel.unmount();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(mocks.fetch).toHaveBeenCalledTimes(2);
    expect(signal).toBeDefined();
  });

  it('aborts old symbols and ignores late responses after a switch', async () => {
    let resolveOld!: (value: IntradaySnapshot) => void;
    mocks.fetch.mockReturnValueOnce(new Promise<IntradaySnapshot>(resolve => { resolveOld = resolve; }));
    mocks.fetch.mockResolvedValue(snapshot('MSFT.US', at, 120));
    const panel = mountPanel();
    const oldSignal = mocks.fetch.mock.calls[0]?.[2] as AbortSignal;
    await panel.setProps({ symbol: 'MSFT.US' });
    await flushPromises();
    expect(oldSignal.aborted).toBe(true);
    resolveOld(snapshot('AAPL.US', at, 999));
    await flushPromises();
    expect(panel.text()).toContain('120');
    expect(panel.text()).not.toContain('999');
    panel.unmount();
  });
});
