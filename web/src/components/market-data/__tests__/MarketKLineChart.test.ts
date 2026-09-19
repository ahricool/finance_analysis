import { mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DataLoader, KLineData } from 'klinecharts';
import MarketKLineChart from '../MarketKLineChart.vue';
import { useTheme } from '@/composables/useTheme';

const chart = vi.hoisted(() => ({
  setStyles: vi.fn(), setSymbol: vi.fn(), setPeriod: vi.fn(), setDataLoader: vi.fn(),
  createIndicator: vi.fn(), resetData: vi.fn(), resize: vi.fn(),
}));
const lifecycle = vi.hoisted(() => ({ dispose: vi.fn(), init: vi.fn() }));
vi.mock('klinecharts', () => ({ init: lifecycle.init, dispose: lifecycle.dispose }));
const bar: KLineData = { timestamp: 1000, open: 1, high: 3, low: 1, close: 2, volume: 5 };
function loader() { return chart.setDataLoader.mock.lastCall![0] as DataLoader; }
const context = { symbol: { ticker: 'AAPL.US', pricePrecision: 2, volumePrecision: 0 }, period: { type: 'day' as const, span: 1 } };

describe('MarketKLineChart v10 lifecycle', () => {
  beforeEach(() => { vi.clearAllMocks(); lifecycle.init.mockReturnValue(chart); });
  it('loads OHLCV, adds VOL and daily MA, resets on source/symbol/period and disposes', async () => {
    const wrapper = mount(MarketKLineChart, { props: { symbol: 'AAPL.US', period: '1d', bars: [bar] } });
    expect(chart.setSymbol).toHaveBeenCalledWith(context.symbol);
    expect(chart.setPeriod).toHaveBeenCalledWith(context.period);
    expect(chart.createIndicator).toHaveBeenCalledWith('VOL');
    expect(chart.createIndicator).toHaveBeenCalledWith({ name: 'MA', calcParams: [5, 10, 20], paneId: 'candle_pane' });
    const callback = vi.fn();
    loader().getBars({ ...context, type: 'init', timestamp: null, callback });
    expect(callback).toHaveBeenLastCalledWith([bar], false);
    loader().getBars({ ...context, type: 'forward', timestamp: 1000, callback });
    expect(callback).toHaveBeenLastCalledWith([], false);
    await wrapper.setProps({ bars: [] });
    expect(chart.resetData).toHaveBeenCalled();
    await wrapper.setProps({ symbol: '600519.SH', period: '1m', sourceKey: 'new' });
    expect(lifecycle.dispose).toHaveBeenCalledTimes(1);
    expect(chart.setSymbol.mock.lastCall![0].ticker).toBe('600519.SH');
    loader().getBars({ ...context, type: 'init', timestamp: null, callback });
    expect(callback).toHaveBeenLastCalledWith([], false);
    wrapper.unmount();
    expect(lifecycle.dispose).toHaveBeenCalledTimes(2);
  });
  it('pushes live bars only while subscribed and follows theme', async () => {
    const wrapper = mount(MarketKLineChart, { props: { symbol: 'BTCUSDT', period: '1m', bars: [bar] } });
    const callback = vi.fn();
    loader().subscribeBar!({ ...context, callback });
    await wrapper.setProps({ current: { ...bar, timestamp: 2000 } });
    expect(callback).toHaveBeenCalledTimes(1);
    loader().unsubscribeBar!(context);
    await wrapper.setProps({ current: { ...bar, timestamp: 3000 } });
    expect(callback).toHaveBeenCalledTimes(1);
    const { setTheme } = useTheme();
    setTheme('dark');
    await wrapper.vm.$nextTick();
    expect(chart.setStyles).toHaveBeenCalledWith('dark');
    expect(chart.setStyles.mock.lastCall![0].candle.bar.upColor).toBe('#e86464');
    setTheme('light');
    await wrapper.vm.$nextTick();
    expect(chart.setStyles).toHaveBeenCalledWith('light');
    wrapper.unmount();
  });
});
