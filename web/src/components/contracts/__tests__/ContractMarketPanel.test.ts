import { mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ContractMarketPanel from '../ContractMarketPanel.vue';
import type { Candle, ContractQuote } from '@/api/contracts';

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
  it('exposes loading and empty states and changes periods on demand', async () => {
    const panel = render();
    expect(panel.text()).toContain('暂无 K 线');
    await panel.setProps({ loading: true });
    expect(panel.text()).toContain('行情加载中');
    await panel.findAll('button').find(item => item.text() === '日 K')!.trigger('click');
    expect(panel.emitted('update:interval')).toEqual([['1d']]);
    panel.unmount();
  });
});
