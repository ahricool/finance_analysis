import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { registerOverlay, utils, type CandleStyle, type CandleTooltipLegendsCustomCallback, type DataLoader,
  type FormatDate, type KLineData, type OverlayCreate, type OverlayCreateFiguresCallbackParams } from 'klinecharts';
import MarketKLineChart from '../MarketKLineChart.vue';
import { useTheme } from '@/composables/useTheme';
import { fetchMinuteForecast } from '@/api/minuteForecast';

const chart = vi.hoisted(() => ({
  removeOverlay: vi.fn(), createOverlay: vi.fn((overlays: { id?: string }[]) => overlays.map(overlay => overlay.id)),
  setStyles: vi.fn(), setSymbol: vi.fn(), setPeriod: vi.fn(), setDataLoader: vi.fn(),
  getDom: vi.fn(), getSize: vi.fn(() => ({ width: 1000 })), convertToPixel: vi.fn(() => ({ x: 995 })), scrollByDistance: vi.fn(),
  scrollToTimestamp: vi.fn(), scrollToRealTime: vi.fn(), createIndicator: vi.fn(), resetData: vi.fn(), resize: vi.fn(),
  overrideYAxis: vi.fn(), overrideXAxis: vi.fn(), setBarSpace: vi.fn(), setOffsetRightDistance: vi.fn(),
  setScrollEnabled: vi.fn(), setZoomEnabled: vi.fn(),
  getDataList: vi.fn<() => KLineData[]>(), getVisibleRange: vi.fn(),
  getBarSpace: vi.fn(() => ({ bar: 10, halfGapBar: 3 })),
}));
const lifecycle = vi.hoisted(() => ({ dispose: vi.fn(), init: vi.fn() }));
vi.mock('klinecharts', () => ({ init: lifecycle.init, dispose: lifecycle.dispose,
  registerOverlay: vi.fn(),
  utils: { formatDate: vi.fn(() => 'formatted') } }));
vi.mock('@/api/minuteForecast', () => ({ fetchMinuteForecast: vi.fn() }));
const bar: KLineData = { timestamp: 1000, open: 1, high: 3, low: 1, close: 2, volume: 5 };
function loader() { return chart.setDataLoader.mock.lastCall![0] as DataLoader; }
const context = { symbol: { ticker: 'AAPL.US', pricePrecision: 2, volumePrecision: 0 }, period: { type: 'day' as const, span: 1 } };

describe('MarketKLineChart v10 lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks(); lifecycle.init.mockReturnValue(chart);
    vi.mocked(fetchMinuteForecast).mockResolvedValue({ enabled: false, forecast: null, comparison: null });
  });
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
  it('navigates to the marked date and supports repeated latest requests after panning', async () => {
    const wrapper = mount(MarketKLineChart, { props: { symbol: 'AAPL.US', period: '1d', bars: [bar] } });
    await wrapper.setProps({ focusTimestamp: 1000, focusRequest: 1 });
    expect(chart.scrollToTimestamp).toHaveBeenLastCalledWith(1000);
    expect(chart.scrollByDistance).toHaveBeenLastCalledWith(-495);
    await wrapper.setProps({ focusTimestamp: undefined, focusRequest: 2 });
    await wrapper.setProps({ focusRequest: 3 });
    expect(chart.scrollToRealTime).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });
  it('shows a marker hint on hover and clears obsolete evidence after a live refresh', async () => {
    const annotation = { name: 'optionsStructureMark', id: 'structure-event', hint: '箱体向上突破 · 待确认' };
    const wrapper = mount(MarketKLineChart, { props: { symbol: 'SPY.US', period: '1m', bars: [bar], overlays: [annotation] } });
    const event = { chart: { getSize: () => ({ left: 0, top: 0, width: 800, height: 300 }) }, x: 70, y: 30 };
    const drawn = () => chart.createOverlay.mock.lastCall![0][0] as OverlayCreate;
    drawn().onMouseMove!(event as never);
    await wrapper.vm.$nextTick();
    expect(wrapper.get('[role=tooltip]').text()).toBe(annotation.hint);
    await wrapper.setProps({ overlays: [{ ...annotation, hint: '箱体向上突破 · 已确认' }] });
    expect(wrapper.find('[role=tooltip]').exists()).toBe(false);
    drawn().onMouseMove!(event as never);
    await wrapper.vm.$nextTick();
    expect(wrapper.get('[role=tooltip]').text()).toContain('已确认');
    drawn().onMouseLeave!(event as never);
    await wrapper.vm.$nextTick();
    expect(wrapper.find('[role=tooltip]').exists()).toBe(false);
    wrapper.unmount();
  });
  it('plots the minute forecast as a separately removable overlay without changing OHLC data', async () => {
    const timestamp = Math.floor(Date.now() / 60_000) * 60_000 - 60_000;
    const actual = { ...bar, timestamp };
    const predicted = { timestamp: timestamp + 60_000, open: 2, high: 4, low: 2, close: 3 };
    vi.mocked(fetchMinuteForecast).mockResolvedValueOnce({ enabled: true, comparison: null, forecast: {
      symbol: 'BTCUSDT', model: 'small', weightsRevision: 'fixed', anchor: timestamp,
      anchorClose: 2, generatedAt: Date.now(), lookback: 60, bars: [predicted],
    } });
    const wrapper = mount(MarketKLineChart, { props: { symbol: 'BTCUSDT', period: '1m', bars: [actual] } });
    await flushPromises();
    expect(chart.createOverlay).toHaveBeenLastCalledWith([expect.objectContaining({ id: 'minute-forecast', points: [
      ...[2, 4, 2, 3].map(value => ({ timestamp: predicted.timestamp, value })),
    ] })]);
    const overlay = chart.createOverlay.mock.lastCall![0][0] as OverlayCreate;
    const figures = vi.mocked(registerOverlay).mock.lastCall![0].createPointFigures!({
      chart, overlay, coordinates: [{ x: 20, y: 30 }, { x: 20, y: 10 }, { x: 20, y: 30 }, { x: 20, y: 20 }],
    } as unknown as OverlayCreateFiguresCallbackParams<unknown>);
    expect(figures).toHaveLength(2);
    if (!Array.isArray(figures)) throw new Error('Expected separate wick and body figures');
    expect(figures[0]).toMatchObject({ type: 'line', styles: { color: '#dc2626' } });
    expect(figures[1]).toMatchObject({ type: 'line', styles: { color: '#dc2626', style: 'solid' },
      attrs: { coordinates: [{ x: 17, y: 20 }, { x: 23, y: 20 }, { x: 23, y: 30 },
        { x: 17, y: 30 }, { x: 17, y: 20 }] } });
    const callback = vi.fn();
    loader().getBars({ ...context, type: 'init', timestamp: null, callback });
    expect(callback).toHaveBeenLastCalledWith([actual], false);
    expect(wrapper.get('[data-testid="minute-forecast"]').text()).toContain('Kronos small');
    await wrapper.get('input[type="checkbox"]').setValue(false);
    expect(chart.removeOverlay).toHaveBeenLastCalledWith({ id: 'minute-forecast' });
    await wrapper.setProps({ period: '5m' });
    expect(wrapper.find('[data-testid="minute-forecast"]').exists()).toBe(false);
    expect(vi.mocked(fetchMinuteForecast)).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });
  it('packs future daily candles into consecutive trading slots and labels them with the actual sessions', async () => {
    const anchor = { ...bar, timestamp: Date.parse('2026-11-25T00:00:00Z') };
    const actual = { ...bar, timestamp: Date.parse('2026-11-27T00:00:00Z') };
    const wrapper = mount(MarketKLineChart, { props: { symbol: 'AAPL.US', period: '1d', bars: [anchor, actual],
      dailyForecast: { symbol: 'AAPL.US', anchorDate: '2026-11-25', anchorClose: 2,
        generatedAt: '2026-11-26T04:00:00Z', model: 'small', weightsRevision: 'fixed', lookback: 240,
        bars: [{ tradeDate: '2026-11-27', open: 2, high: 5, low: 1, close: 4 },
          { tradeDate: '2026-11-30', open: 3, high: 8, low: 0.5, close: 2.5 },
          { tradeDate: '2026-12-01', open: 3, high: 7, low: 1, close: 2.6 }],
        accuracy: { tradingDate: '2026-11-27', recent: { issuedAt: anchor.timestamp,
          rows: [{ step: 1, close: 2, error: 1, baselineError: 1.2 }] },
          average: [{ step: 1, count: 3, mae: 0.9, baselineMae: 1.3 }] },
      } } });
    const saturday = Date.parse('2026-11-28T00:00:00Z');
    const sunday = Date.parse('2026-11-29T00:00:00Z');
    const monday = Date.parse('2026-11-30T00:00:00Z');
    expect(chart.createOverlay).toHaveBeenLastCalledWith([expect.objectContaining({ id: 'daily-forecast',
      points: [...[3, 8, 0.5, 2.5].map(value => ({ timestamp: saturday, value })),
        ...[3, 7, 1, 2.6].map(value => ({ timestamp: sunday, value }))],
      extendData: { colors: ['#16854e', '#16854e'] },
    })]);
    const label = lifecycle.init.mock.lastCall![1].formatter.formatDate as FormatDate;
    const dateTimeFormat = new Intl.DateTimeFormat('en', { timeZone: 'UTC' });
    label({ timestamp: saturday, type: 'crosshair', dateTimeFormat, template: 'YYYY-MM-DD' });
    expect(utils.formatDate).toHaveBeenLastCalledWith(dateTimeFormat, monday, 'YYYY-MM-DD');
    label({ timestamp: sunday, type: 'xAxis', dateTimeFormat, template: 'MM-DD' });
    expect(utils.formatDate).toHaveBeenLastCalledWith(dateTimeFormat, Date.parse('2026-12-01T00:00:00Z'), 'MM-DD');
    expect(label({ timestamp: monday, type: 'crosshair', dateTimeFormat, template: 'YYYY-MM-DD' })).toBe('');
    expect(chart.setOffsetRightDistance).toHaveBeenLastCalledWith(30);
    const callback = vi.fn();
    loader().getBars({ ...context, type: 'init', timestamp: null, callback });
    expect(callback).toHaveBeenLastCalledWith([anchor, actual], false);
    const panel = wrapper.get('[data-testid="daily-forecast"]');
    expect(panel.text()).toContain('2026-11-30');
    expect(panel.findAll('details')[0]?.text()).not.toContain('2026-11-28');
    expect(panel.text()).toContain('平均误差');
    expect(panel.text()).toContain('3 个样本');
    chart.getDataList.mockReturnValue([anchor, actual]);
    chart.getVisibleRange.mockReturnValue({ to: 2 });
    const range = chart.overrideYAxis.mock.lastCall![0].createRange({ defaultRange: { from: 1, to: 3 } });
    expect(range.from).toBeLessThanOrEqual(0.5);
    expect(range.to).toBeGreaterThanOrEqual(8);
    await wrapper.setProps({ period: '1w' });
    expect(wrapper.find('[data-testid="daily-forecast"]').exists()).toBe(false);
    await wrapper.setProps({ period: '1d', bars: [actual] });
    expect(wrapper.find('[data-testid="daily-forecast"]').exists()).toBe(false);
    wrapper.unmount();
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

  it('labels a historical close replay and removes it when a newer real candle arrives', async () => {
    vi.mocked(fetchMinuteForecast).mockResolvedValueOnce({ enabled: true, comparison: null, forecast: {
      symbol: 'QQQ.US', model: 'small', weightsRevision: 'fixed', anchor: bar.timestamp,
      anchorClose: 2, generatedAt: Date.now(), lookback: 30, closeReplay: true,
      bars: [{ timestamp: 61_000, open: 2, high: 4, low: 2, close: 3 }],
    } });
    const wrapper = mount(MarketKLineChart, { props: { symbol: 'QQQ.US', period: '1m', bars: [bar] } });
    await flushPromises();
    expect(chart.createOverlay).toHaveBeenCalled();
    expect(wrapper.get('[data-testid="minute-forecast"]').text()).toContain('收盘试算');
    await wrapper.setProps({ bars: [bar, { ...bar, timestamp: 61_000 }] });
    expect(chart.removeOverlay).toHaveBeenCalledWith({ id: 'minute-forecast' });
    expect(wrapper.get('[data-testid="minute-forecast"]').text()).not.toContain('收盘试算');
    wrapper.unmount();
  });

  it('shows ten forecast rows and the sample-weighted daily error separately from the latest batch', async () => {
    const start = Math.floor(Date.now() / 60_000) * 60_000;
    const actual = { ...bar, timestamp: start - 60_000 };
    vi.mocked(fetchMinuteForecast).mockResolvedValueOnce({
      enabled: true,
      comparison: null,
      forecast: { symbol: 'QQQ.US', model: 'small', weightsRevision: 'fixed', anchor: actual.timestamp,
        anchorClose: 2, generatedAt: start, lookback: 240, bars: Array.from({ length: 10 }, (_, index) => ({
          timestamp: start + index * 60_000, open: 2, high: 4, low: 2, close: 3,
        })) },
      accuracy: { tradingDate: '2026-11-20', recent: { issuedAt: start - 15 * 60_000,
        rows: [{ step: 10, close: 5, error: 2, baselineError: 3 }] }, daily: [
        { step: 1, count: 3, mae: 1, baselineMae: 2 }, { step: 10, count: 1, mae: 5, baselineMae: 6 },
      ] },
    });
    const wrapper = mount(MarketKLineChart, { props: { symbol: 'QQQ.US', period: '1m', bars: [actual] } });
    await flushPromises();
    const panel = wrapper.get('[data-testid="minute-forecast"]');
    const summary = panel.findAll('dl > div');
    expect(summary[0]?.text()).toContain('10 根');
    expect(summary[1]?.text()).toContain('基线 3 · 1 个样本');
    expect(summary[2]?.get('strong').text()).toBe('2');
    expect(summary[2]?.text()).toContain('基线 3 · 4 个样本');
    expect(panel.findAll('details')[0]?.findAll('li')).toHaveLength(10);
    expect(panel.findAll('details')[1]?.text()).toContain('+10 分钟');
    expect(chart.createOverlay.mock.lastCall?.[0]?.[0]).toHaveProperty('points.length', 40);
    wrapper.unmount();
  });

  it('updates polled candles in place and restores the visible minute after a history correction', async () => {
    let displayed: KLineData[] = [];
    chart.getDataList.mockImplementation(() => displayed);
    const wrapper = mount(MarketKLineChart, { props: { symbol: 'SPY.US', period: '1m', liveSnapshot: true,
      bars: [bar], current: { ...bar, timestamp: 2000 } } });
    const push = vi.fn((candle: KLineData) => {
      if (displayed.at(-1)?.timestamp === candle.timestamp) displayed[displayed.length - 1] = candle;
      else displayed.push(candle);
    });
    const load = () => loader().getBars({ ...context, type: 'init', timestamp: null,
      callback: candles => { displayed = candles; } });
    load();
    loader().subscribeBar!({ ...context, callback: push });
    await wrapper.setProps({ bars: [{ ...bar }], current: { ...bar, timestamp: 2000 } });
    expect(push).not.toHaveBeenCalled();
    const finalized = { ...bar, timestamp: 2000, volume: 9 };
    const current = { ...bar, timestamp: 3000 };
    await wrapper.setProps({ bars: [bar, finalized], current });
    expect(push.mock.calls).toEqual([[finalized], [current]]);
    expect(chart.resetData).not.toHaveBeenCalled();
    expect(chart.scrollToRealTime).not.toHaveBeenCalled();

    chart.getVisibleRange.mockReturnValue({ from: 0, to: 1 });
    chart.convertToPixel.mockReturnValueOnce({ x: 600 }).mockReturnValueOnce({ x: 200 });
    chart.resetData.mockImplementationOnce(load);
    const corrected = { ...bar, volume: 25 };
    await wrapper.setProps({ bars: [corrected, finalized] });
    expect(displayed).toEqual([corrected, finalized, current]);
    expect(chart.convertToPixel.mock.calls).toEqual(Array(2).fill([{ timestamp: bar.timestamp }, { paneId: 'candle_pane' }]));
    expect(chart.scrollByDistance).toHaveBeenCalledWith(400);

    // A capped window can drop its oldest candle as a new one arrives.
    chart.getVisibleRange.mockReturnValue({ from: 0, to: displayed.length });
    chart.convertToPixel.mockClear();
    chart.resetData.mockImplementationOnce(load);
    const appended = { ...bar, timestamp: 4000 };
    await wrapper.setProps({ bars: [finalized, current], current: appended });
    expect(displayed).toEqual([finalized, current, appended]);
    expect(chart.convertToPixel.mock.calls).toEqual([
      [{ timestamp: current.timestamp }, { paneId: 'candle_pane' }],
      [{ timestamp: appended.timestamp }, { paneId: 'candle_pane' }],
    ]);
    await wrapper.setProps({ focusTimestamp: finalized.timestamp, focusRequest: 1 });
    expect(chart.scrollToTimestamp).toHaveBeenCalledWith(finalized.timestamp);
    await wrapper.setProps({ focusTimestamp: undefined });
    expect(chart.scrollToRealTime).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it.each([
    { previousClose: 100, open: 110, close: 105, high: 110, low: 99, change: '+5.00%', amplitude: '11.00%', color: 'upColor' },
    { previousClose: 100, open: 90, close: 95, high: 110, low: 90, change: '-5.00%', amplitude: '20.00%', color: 'downColor' },
    { previousClose: 100, open: 95, close: 100, high: 100, low: 95, change: '0.00%', amplitude: '5.00%', color: 'noChangeColor' },
    { previousClose: null, open: 100, close: 105, high: 110, low: 99, change: '--', amplitude: '--', color: null },
    { previousClose: 0, open: 100, close: 105, high: 110, low: 99, change: '--', amplitude: '--', color: null },
    { previousClose: -100, open: 100, close: 105, high: 110, low: 99, change: '--', amplitude: '--', color: null },
    { previousClose: NaN, open: 100, close: 105, high: 110, low: 99, change: '--', amplitude: '--', color: null },
    { previousClose: Infinity, open: 100, close: 105, high: 110, low: 99, change: '--', amplitude: '--', color: null },
    { previousClose: 100, open: 100, close: Infinity, high: NaN, low: 99, change: '--', amplitude: '--', color: null },
  ])('formats percentages against previous close: $previousClose / $change', async (sample) => {
    const wrapper = mount(MarketKLineChart, { props: { symbol: 'AAPL.US', period: '1d', bars: [bar] } });
    const { setTheme } = useTheme();
    for (const theme of ['dark', 'light'] as const) {
      setTheme(theme);
      await wrapper.vm.$nextTick();
      const candle = chart.setStyles.mock.lastCall![0].candle;
      expect(candle.tooltip).toMatchObject({ showRule: 'follow_cross', showType: 'rect' });
      const template = candle.tooltip.legend.template as CandleTooltipLegendsCustomCallback;
      const styles = { ...candle, tooltip: { ...candle.tooltip,
        legend: { ...candle.tooltip.legend, color: 'neutral' } } } as CandleStyle;
      // Gap opens must not determine the percentage or its color.
      const rows = template({ prev: sample.previousClose === null ? null : { ...bar, close: sample.previousClose }, current: { ...bar,
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

it('keeps the previous close visible through a gap open and labels the full CN session without fake bars', async () => {
  lifecycle.init.mockReturnValue(chart);
  const open = Date.parse('2026-10-23T09:30:00+08:00');
  const session = { open, close: open + 330 * 60_000, breakStart: open + 120 * 60_000, breakEnd: open + 210 * 60_000 };
  const candles = [{ ...bar, timestamp: open, open: 110, high: 112, low: 109, close: 111 }];
  const wrapper = mount(MarketKLineChart, { props: { symbol: '600000.SH', period: '1m', bars: candles,
    referencePrice: 100, session, timezone: 'Asia/Shanghai' } });
  const createRange = chart.overrideYAxis.mock.lastCall![0].createRange;
  const range = createRange({ defaultRange: { from: 109, to: 112 } });
  expect(range.from).toBeLessThan(100);
  expect(range.to).toBeGreaterThan(112);
  const ticks = chart.overrideXAxis.mock.lastCall![0].createTicks({ bounding: { width: 1000 } });
  expect(ticks.map((tick: { text: string }) => tick.text)).toEqual(['09:30', '11:30 / 13:00', '15:00']);
  const callback = vi.fn();
  loader().getBars({ ...context, type: 'init', timestamp: null, callback });
  expect(callback).toHaveBeenLastCalledWith(candles, false);
  expect(chart.setZoomEnabled).toHaveBeenLastCalledWith(false);
  const dateFormatter = lifecycle.init.mock.lastCall![1].formatter.formatDate;
  expect(dateFormatter({ type: 'crosshair', timestamp: open + 180 * 60_000 })).toBe('');
  expect(dateFormatter({ type: 'crosshair', timestamp: open })).toBe('formatted');
  const candle = chart.setStyles.mock.lastCall![0].candle;
  const template = candle.tooltip.legend.template as CandleTooltipLegendsCustomCallback;
  const tooltip = template({ prev: { ...bar, close: 110 }, current: candles[0]!, next: null },
    { ...candle, tooltip: { ...candle.tooltip, legend: { ...candle.tooltip.legend, color: 'neutral' } } } as CandleStyle);
  expect(tooltip.find(row => row.title === '涨跌')?.value).toMatchObject({ text: '+11.00%' });
  wrapper.unmount();
});

it('replaces only owned overlays across independent groups and clears removed props', async () => {
  lifecycle.init.mockReturnValue(chart);
  const overlays = [
    { name: 'tradeBst', id: 'bst-1', groupId: 'strategy-markers' },
    { name: 'tradeBst', id: 'research-date', groupId: 'research-date' },
    { name: 'dailyPattern', id: 'daily-pattern-1', groupId: 'daily-patterns' },
  ];
  const wrapper = mount(MarketKLineChart, { props: { symbol: 'AAPL.US', period: '1d', bars: [bar], overlays } });
  expect(chart.createOverlay).toHaveBeenLastCalledWith(overlays);
  chart.removeOverlay.mockClear();
  await wrapper.setProps({ overlays: overlays.slice(0, 2) });
  expect(chart.removeOverlay.mock.calls).toEqual([
    [{ id: 'bst-1' }], [{ id: 'research-date' }], [{ id: 'daily-pattern-1' }],
  ]);
  expect(chart.createOverlay).toHaveBeenLastCalledWith(overlays.slice(0, 2));
  chart.removeOverlay.mockClear();
  await wrapper.setProps({ overlays: undefined });
  expect(chart.removeOverlay.mock.calls).toEqual([[{ id: 'bst-1' }], [{ id: 'research-date' }]]);
  await wrapper.setProps({ overlays, sourceKey: 'new' });
  expect(chart.createOverlay).toHaveBeenLastCalledWith(overlays);
  wrapper.unmount();
});
