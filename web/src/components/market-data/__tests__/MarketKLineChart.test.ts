import { mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CandleStyle, CandleTooltipLegendsCustomCallback, DataLoader, KLineData } from 'klinecharts';
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
    const wrapper = mount(MarketKLineChart, { props: { symbol: 'AAPL.US', period: '1d', pricePrecision: 2, bars: [bar] } });
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
    await wrapper.setProps({ symbol: '600519.SH', period: '1m', sourceKey: 'new', pricePrecision: 3 });
    expect(lifecycle.dispose).toHaveBeenCalledTimes(1);
    expect(chart.setSymbol.mock.lastCall![0].ticker).toBe('600519.SH');
    expect(chart.setSymbol.mock.lastCall![0].pricePrecision).toBe(3);
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

  it.each([
    { open: 100, close: 105, high: 110, low: 99, change: '+5.00%', amplitude: '11.00%', color: 'upColor' },
    { open: 100, close: 95, high: 110, low: 90, change: '-5.00%', amplitude: '20.00%', color: 'downColor' },
    { open: 100, close: 100, high: 100, low: 100, change: '0.00%', amplitude: '0.00%', color: 'noChangeColor' },
    { open: 0, close: 105, high: 110, low: 99, change: '--', amplitude: '--', color: null },
    { open: NaN, close: 105, high: 110, low: 99, change: '--', amplitude: '--', color: null },
    { open: 100, close: Infinity, high: NaN, low: 99, change: '--', amplitude: '--', color: null },
  ])('formats candle-relative percentages: $change / $amplitude', async (sample) => {
    const wrapper = mount(MarketKLineChart, { props: { symbol: 'BTCUSDT', period: '15m', bars: [bar] } });
    const { setTheme } = useTheme();
    for (const theme of ['dark', 'light'] as const) {
      setTheme(theme);
      await wrapper.vm.$nextTick();
      const candle = chart.setStyles.mock.lastCall![0].candle;
      expect(candle.tooltip).toMatchObject({ showRule: 'follow_cross', showType: 'rect' });
      const template = candle.tooltip.legend.template as CandleTooltipLegendsCustomCallback;
      const styles = { ...candle, tooltip: { ...candle.tooltip,
        legend: { ...candle.tooltip.legend, color: 'neutral' } } } as CandleStyle;
      // A previous close of 200 would produce a loss for the positive candle.
      const rows = template({ prev: { ...bar, close: 200 }, current: { ...bar,
        open: sample.open, close: sample.close, high: sample.high, low: sample.low }, next: null }, styles);
      expect(rows).toEqual([
        { title: '时间', value: '{time}' },
        { title: '开盘', value: '{open}' },
        { title: '最高', value: '{high}' },
        { title: '最低', value: '{low}' },
        { title: '收盘', value: '{close}' },
        { title: '涨跌', value: { text: sample.change, color: sample.color ? candle.bar[sample.color] : 'neutral' } },
        { title: '振幅', value: sample.amplitude },
        { title: '成交量', value: '{volume}' },
      ]);
    }
    wrapper.unmount();
  });
});
