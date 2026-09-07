import { flushPromises, mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import BtcKlineChart from '../BtcKlineChart.vue';
import type { CryptoKline } from '@/types/crypto';

const methods = vi.hoisted(() => ({ setOption: vi.fn() }));
vi.mock('vue-echarts', () => ({ default: {
  props: ['option'], setup: () => methods, template: '<div />',
} }));
const row: CryptoKline = {
  symbol: 'BTCUSDT', interval: '1m', source: 'binance', openTime: '2026-09-01T00:00:00Z',
  closeTime: '2026-09-01T00:01:00Z', open: '100', high: '103', low: '99', close: '101', volume: '1',
  quoteVolume: '100', tradeCount: 2, takerBuyVolume: '0.5', takerBuyQuoteVolume: '50', closed: true,
};
describe('BTC incremental chart', () => {
  it('initializes axes before updates and changes only the current series on live ticks', async () => {
    const wrapper = mount(BtcKlineChart, { props: { candles: [row], current: null } });
    await flushPromises();
    expect(methods.setOption.mock.calls[0]![0]).toHaveProperty('xAxis');
    methods.setOption.mockClear();
    const current = { ...row, openTime: '2026-09-01T00:01:00Z', closed: false };
    await wrapper.setProps({ current });
    await wrapper.setProps({ current: { ...current, close: '102' } });
    expect(methods.setOption).toHaveBeenCalledTimes(2);
    for (const [option] of methods.setOption.mock.calls) {
      expect(option.series).toHaveLength(1);
      expect(option.series[0].id).toBe('current');
      expect(option.series[0].data).toHaveLength(1);
    }
    wrapper.unmount();
  });
});
