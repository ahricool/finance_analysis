import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import BtcKlineChart from '../BtcKlineChart.vue';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import type { CryptoSnapshot } from '@/types/crypto';
import type { CryptoKline } from '@/types/binance';

const row: CryptoKline = {
  symbol: 'BTCUSDT', interval: '1m', source: 'binance', openTime: '2026-09-01T00:00:00Z',
  closeTime: '2026-09-01T00:01:00Z', open: '100', high: '103', low: '99', close: '101', volume: '1',
  quoteVolume: '100', tradeCount: 2, takerBuyVolume: '0.5', takerBuyQuoteVolume: '50', closed: true,
};
describe('BTC chart data mapping', () => {
  it('keeps historical and current minute OHLCV separate, ignoring stale/closed current', async () => {
    const wrapper = mount(BtcKlineChart, { props: { candles: [row], current: null },
      global: { stubs: { MarketKLineChart: true } } });
    const chart = wrapper.getComponent(MarketKLineChart);
    expect(chart.props('period')).toBe('1m');
    expect(chart.props('pricePrecision')).toBe(2);
    expect(chart.props('bars')).toEqual([{ timestamp: Date.parse(row.openTime), open: 100, high: 103,
      low: 99, close: 101, volume: 1, turnover: 100 }]);
    const current = { ...row, openTime: '2026-09-01T00:01:00Z', closed: false };
    await wrapper.setProps({ current });
    expect(chart.props('current')?.timestamp).toBe(Date.parse(current.openTime));
    await wrapper.setProps({ current: { ...current, close: '102' } });
    expect(chart.props('current')?.close).toBe(102);
    await wrapper.setProps({ candles: [row, { ...current, closed: true }] });
    expect(chart.props('current')).toBeNull();
    await wrapper.setProps({ current: row });
    expect(chart.props('current')).toBeNull();
    wrapper.unmount();
  });
  it('creates BUY/EXIT overlays and reveals details on click', async () => {
    const signal = { action: 'BUY', evaluatedAt: row.openTime, price: '101', positionBefore: '0', positionAfter: '1',
      regime: 'BULL', setup: 'BREAKOUT', reason: 'test entry' } as CryptoSnapshot;
    const wrapper = mount(BtcKlineChart, { props: { candles: [row], current: null, signals: [signal] },
      global: { stubs: { MarketKLineChart: true } } });
    const overlay = wrapper.getComponent(MarketKLineChart).props('overlays')![0]!;
    expect(overlay.points).toEqual([{ timestamp: Date.parse(row.openTime), value: 101 }]);
    expect((overlay.extendData as { label: string }).label).toBe('↑ BUY');
    overlay.onClick!({} as never); await wrapper.vm.$nextTick();
    expect(wrapper.get('[data-testid="btc-signal-detail"]').text()).toContain('test entry');
    await wrapper.setProps({ signals: [{ ...signal, action: 'EXIT' }] });
    expect((wrapper.getComponent(MarketKLineChart).props('overlays')![0]!.extendData as { label: string }).label).toBe('↓ EXIT');
    wrapper.unmount();
  });

});
