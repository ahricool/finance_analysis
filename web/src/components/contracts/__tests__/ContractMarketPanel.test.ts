import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ContractMarketPanel from '../ContractMarketPanel.vue';
import type { Candle, ContractQuote } from '@/api/contracts';

vi.mock('@/api/contracts', () => ({ contractsApi: {
  depth: vi.fn(async () => ({ timestamp: Date.now(), bids: 200, asks: 330, bids_levels: 2, asks_levels: 3 })),
  history: vi.fn(async () => []),
} }));
const now = Date.parse('2026-11-25T10:20:30Z');
const minute = Math.floor(now / 60_000) * 60_000;
const row: ContractQuote = { symbol: 'BTCUSDT', category: 'COIN', underlying_symbol: 'BTC.CRYPTO', quote: null };
function candle(timestamp: number, price: number): Candle {
  return { timestamp, open: price, high: price, low: price, close: price, volume: 1, turnover: price };
}
const history = Array.from({ length: 20 }, (_, index) => candle(minute - (20 - index) * 60_000, 100));
function render(bars: Candle[] = []) {
  return mount(ContractMarketPanel, { props: { row, interval: '1m', bars, current: null, loading: false, error: null },
    global: { stubs: { MarketKLineChart: true } } });
}
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(now); });
afterEach(() => vi.useRealTimers());

describe('contract inline indicators', () => {
  it('excludes the forming minute from MA and preserves it as chart preview', () => {
    const panel = render([...history, candle(minute, 200)]);
    const chart = panel.findComponent({ name: 'MarketKLineChart' });
    expect(chart.props('bars')).toHaveLength(20);
    expect(chart.props('current')).toMatchObject({ close: 200 });
    expect(chart.props('disableForecast')).toBe(true);
    expect(panel.findAll('dt').find(item => item.text() === 'MA20')?.element.nextElementSibling?.textContent).toBe('100');
    expect(panel.text()).toContain('最新 K 线（预览）');
    panel.unmount();
  });
  it('does not fill a missing minute or absent quote with zero', () => {
    const panel = render([candle(minute - 21 * 60_000, 100), ...history.slice(1)]);
    expect(panel.findAll('dt').find(item => item.text() === 'MA20')?.element.nextElementSibling?.textContent).toBe('—');
    expect(panel.text()).toContain('— / —');
    panel.unmount();
  });
  it('shows mark basis, book spread and actual depth levels without a ticker', async () => {
    const panel = render();
    await panel.setProps({ row: { ...row, mark: { timestamp: now, mark_price: 101, index_price: 100,
      basis: .01, next_funding: now, funding_rate: .0001 }, book: { timestamp: now, bid: 99.99, ask: 100.01, spread_bps: 2 } } });
    await flushPromises();
    expect(panel.text()).toContain('101 / 100 · +1.00%');
    expect(panel.text()).toContain('99.99 / 100.01 · 2 bps');
    expect(panel.text()).toContain('买 200（2 档） / 卖 330（3 档）');
    panel.unmount();
  });
  it('exposes loading and empty states and changes periods on demand', async () => {
    const panel = render();
    expect(panel.text()).toContain('暂无 K 线');
    await panel.setProps({ loading: true });
    expect(panel.text()).toContain('行情加载中');
    await panel.setProps({ interval: '1d' });
    expect(panel.text()).toContain('日线行情');
    panel.unmount();
  });
});
