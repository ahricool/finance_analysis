import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { stocksApi } from '@/api/stocks';
import DailyKLineCard from '../DailyKLineCard.vue';
import MarketKLineChart from '../MarketKLineChart.vue';
import { marketDataApi, type DailyBarsResponse } from '@/api/marketData';
import { candle, dated, engulfing, hammer } from '@/utils/__tests__/fixtures/dailyPatterns';
vi.mock('@/api/stocks', () => ({ stocksApi: { classification: vi.fn().mockRejectedValue(new Error('offline')) } }));
vi.mock('@/api/marketData', () => ({ marketDataApi: { dailyBars: vi.fn() } }));
const result: DailyBarsResponse = { symbol: 'AAPL.US', market: 'US', interval: '1d', adjustment: 'forward', source: 'database',
  items: [{ tradeDate: '2026-09-18', open: 100, high: 105, low: 98, close: 103, volume: 100, amount: 1000 }] };
const options = { props: { symbol: 'AAPL.US', endDate: '2026-09-18' }, global: { stubs: { MarketKLineChart: true } } };
describe('DailyKLineCard', () => {
  beforeEach(() => vi.clearAllMocks());
  it('shows loading, success mapping and passes the historical end date', async () => {
    let resolve!: (value: DailyBarsResponse) => void;
    vi.mocked(marketDataApi.dailyBars).mockReturnValue(new Promise(r => { resolve = r; }));
    const wrapper = mount(DailyKLineCard, options);
    expect(wrapper.text()).toContain('加载中');
    expect(marketDataApi.dailyBars).toHaveBeenCalledWith('AAPL.US', '2026-09-18', undefined, expect.any(AbortSignal));
    resolve({ ...result, items: [{ ...result.items[0]!, low: 1.237 }] }); await flushPromises();
    expect(stocksApi.classification).toHaveBeenCalled();
    expect(wrapper.find('[data-testid="stock-membership-tags"]').exists()).toBe(false);
    expect(wrapper.getComponent(MarketKLineChart).props('pricePrecision')).toBe(3);
    expect(wrapper.getComponent(MarketKLineChart).props('bars')[0]).toEqual({ timestamp: Date.parse('2026-09-18T00:00:00Z'),
      open: 100, high: 105, low: 1.237, close: 103, volume: 100, turnover: 1000 });
    wrapper.unmount();
  });
  it('loads latest bars beyond the highlighted historical date and marks only an exact match', async () => {
    vi.mocked(marketDataApi.dailyBars).mockResolvedValue({ ...result, items: [
      result.items[0]!, { ...result.items[0]!, tradeDate: '2026-09-21' },
    ] });
    const wrapper = mount(DailyKLineCard, { ...options, props: { symbol: 'AAPL.US', highlightDate: '2026-09-18' } });
    await flushPromises();
    expect(marketDataApi.dailyBars).toHaveBeenLastCalledWith('AAPL.US', undefined, '2025-09-18', expect.any(AbortSignal));
    const chart = wrapper.getComponent(MarketKLineChart);
    expect(chart.props('bars')).toHaveLength(2);
    expect(chart.props('overlays')![0]!.points![0]).toEqual({ timestamp: Date.parse('2026-09-18T00:00:00Z'), value: 105 });
    expect(chart.props('focusTimestamp')).toBeUndefined();
    await wrapper.findAll('button').find(button => button.text() === '定位查看日')!.trigger('click');
    expect(chart.props('focusTimestamp')).toBe(Date.parse('2026-09-18T00:00:00Z'));
    await wrapper.findAll('button').find(button => button.text() === '最新行情')!.trigger('click');
    expect(chart.props('focusTimestamp')).toBeUndefined();
    expect(wrapper.text()).toContain('行情至 2026-09-21');
    await wrapper.setProps({ highlightDate: '2026-09-19' });
    await flushPromises();
    expect(wrapper.getComponent(MarketKLineChart).props('overlays')).toHaveLength(0);
    expect(wrapper.text()).toContain('当日无 K 线');
    wrapper.unmount();
  });
  it('keeps fallback history visible and states its actual data date', async () => {
    vi.mocked(marketDataApi.dailyBars).mockResolvedValue({ ...result, historyFallback: true });
    const wrapper = mount(DailyKLineCard, { ...options, props: { symbol: 'AAPL.US', highlightDate: '2026-09-18' } });
    await flushPromises();
    expect(wrapper.getComponent(MarketKLineChart).props('bars')).toHaveLength(1);
    expect(wrapper.text()).toContain('最新历史行情暂不可用，已保留已有数据。当前图表至 2026-09-18');
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    wrapper.unmount();
  });
  it('isolates errors with retry and shows empty state', async () => {
    vi.mocked(marketDataApi.dailyBars).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ ...result, items: [] });
    const wrapper = mount(DailyKLineCard, options);
    await flushPromises();
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
    await wrapper.findAll('button').find(b => b.text() === '重试')!.trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('暂无日 K 数据');
    wrapper.unmount();
  });
  it('aborts old requests, never restores stale data and excludes future bars', async () => {
    let resolve!: (value: DailyBarsResponse) => void;
    vi.mocked(marketDataApi.dailyBars).mockReturnValueOnce(new Promise(r => { resolve = r; }))
      .mockResolvedValueOnce({ ...result, symbol: 'MSFT.US', items: [{ ...result.items[0]!, low: 0.8567 }, { ...result.items[0]!, tradeDate: '2026-09-19' }] });
    const wrapper = mount(DailyKLineCard, options);
    const signal = vi.mocked(marketDataApi.dailyBars).mock.calls[0]![3]!;
    await wrapper.setProps({ symbol: 'MSFT.US' }); await flushPromises();
    expect(signal.aborted).toBe(true);
    resolve(result); await flushPromises();
    expect(wrapper.getComponent(MarketKLineChart).props('symbol')).toBe('MSFT.US');
    expect(wrapper.getComponent(MarketKLineChart).props('bars')).toHaveLength(1);
    expect(wrapper.getComponent(MarketKLineChart).props('pricePrecision')).toBe(4);
    wrapper.unmount();
    expect(vi.mocked(marketDataApi.dailyBars).mock.lastCall![3]!.aborted).toBe(true);
  });
});

describe('DailyKLineCard Price Action', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date('2026-10-01T12:00:00Z')); });
  afterEach(() => vi.useRealTimers());
  const patternOptions = { ...options, props: { symbol: 'AAPL.US', highlightDate: '2026-09-08',
    markers: [{ timestamp: Date.parse('2026-09-08T00:00:00Z'), type: 'B' as const,
      operations: [{ executedAt: '2026-09-08', side: 'BUY' as const, quantity: '10', price: '100' }] }] } };
  it('creates separate pattern/date/BST overlays, shows latest evidence and supports clicks', async () => {
    const items = dated([...engulfing(), ...hammer()]);
    vi.mocked(marketDataApi.dailyBars).mockResolvedValue({ ...result, items });
    const wrapper = mount(DailyKLineCard, patternOptions); await flushPromises();
    const overlays = wrapper.getComponent(MarketKLineChart).props('overlays')!;
    expect(overlays.map(overlay => overlay.groupId)).toEqual(expect.arrayContaining(['daily-patterns', 'research-date', 'strategy-markers']));
    const pattern = overlays.find(overlay => overlay.id === 'daily-pattern-2026-09-08')!;
    expect(pattern.points![0]!.value).toBe(97.5);
    expect(pattern.extendData).toMatchObject({ type: 'bullish_engulfing', confirmed: true });
    expect(wrapper.get('[data-testid="daily-pattern-detail"]').text()).toContain('锤子线');
    pattern.onClick!({} as never); await wrapper.vm.$nextTick();
    const detail = wrapper.get('[data-testid="daily-pattern-detail"]');
    expect(detail.text()).toContain('看涨吞没');
    expect(detail.text()).toContain('阳线实体完整吞没');
    expect(detail.text()).toContain('7 个交易日前');
    expect(detail.text()).toContain('Confirmed');
    overlays.find(overlay => overlay.groupId === 'strategy-markers')!.onClick!({} as never);
    await wrapper.vm.$nextTick();
    expect(wrapper.get('[data-testid="trade-marker-detail"]').text()).toContain('买入10');
    expect(wrapper.get('[data-testid="daily-pattern-detail"]').text()).toContain('看涨吞没');
    expect(marketDataApi.dailyBars).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });
  it('shows Preview for the market-local current day', async () => {
    vi.setSystemTime(new Date('2026-09-09T02:00:00Z'));
    vi.mocked(marketDataApi.dailyBars).mockResolvedValue({ ...result, items: engulfing() });
    const wrapper = mount(DailyKLineCard, patternOptions); await flushPromises();
    expect(wrapper.text()).toContain('Preview / 形成中');
    expect(wrapper.getComponent(MarketKLineChart).props('overlays')!.find(overlay => overlay.groupId === 'daily-patterns')!.extendData).toMatchObject({ confirmed: false });
    wrapper.unmount();
  });
  it('limits summary to three events in the last twenty loaded sessions, while older markers remain clickable', async () => {
    const items = dated([...engulfing(), ...engulfing(), ...engulfing(), ...engulfing()]);
    vi.mocked(marketDataApi.dailyBars).mockResolvedValue({ ...result, items });
    const wrapper = mount(DailyKLineCard, options); await flushPromises();
    const summary = wrapper.get('[data-testid="daily-pattern-summary"]');
    expect(summary.findAll('button')).toHaveLength(2); // endDate truncates the supplied response at Sep 18
    await wrapper.setProps({ endDate: undefined }); await flushPromises();
    expect(wrapper.get('[data-testid="daily-pattern-summary"]').findAll('button')).toHaveLength(3);
    expect(wrapper.get('[data-testid="daily-pattern-detail"]').text()).toContain('2026-10-02');
    wrapper.unmount();
  });
  it('shows the no-pattern message when old events fall outside the recent window', async () => {
    const items = dated([...engulfing(), ...Array.from({ length: 20 }, () => candle(100, 100))]);
    vi.mocked(marketDataApi.dailyBars).mockResolvedValue({ ...result, items });
    const wrapper = mount(DailyKLineCard, { ...options, props: { symbol: 'AAPL.US' } }); await flushPromises();
    expect(wrapper.text()).toContain('最近未发现高置信度');
    expect(wrapper.find('[data-testid="daily-pattern-detail"]').exists()).toBe(false);
    const overlay = wrapper.getComponent(MarketKLineChart).props('overlays')!.find(overlay => overlay.groupId === 'daily-patterns')!;
    overlay.onClick!({} as never); await wrapper.vm.$nextTick();
    expect(wrapper.get('[data-testid="daily-pattern-detail"]').text()).toContain('看涨吞没');
    wrapper.unmount();
  });
  it('clears selections and old overlays on symbol/endDate changes, loading, error and empty responses', async () => {
    vi.mocked(marketDataApi.dailyBars).mockResolvedValueOnce({ ...result, items: engulfing() });
    const wrapper = mount(DailyKLineCard, patternOptions); await flushPromises();
    const overlays = wrapper.getComponent(MarketKLineChart).props('overlays')!;
    overlays.find(overlay => overlay.groupId === 'daily-patterns')!.onClick!({} as never);
    overlays.find(overlay => overlay.groupId === 'strategy-markers')!.onClick!({} as never);
    let resolve!: (value: DailyBarsResponse) => void;
    vi.mocked(marketDataApi.dailyBars).mockReturnValueOnce(new Promise(r => { resolve = r; }));
    await wrapper.setProps({ symbol: 'MSFT.US', markers: [], highlightDate: undefined });
    expect(wrapper.text()).toContain('加载中');
    expect(wrapper.find('[data-testid="daily-pattern-summary"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="trade-marker-detail"]').exists()).toBe(false);
    resolve(result); await flushPromises();
    expect(wrapper.getComponent(MarketKLineChart).props('overlays')).toEqual([]);
    expect(wrapper.text()).toContain('最近未发现高置信度');
    vi.mocked(marketDataApi.dailyBars).mockRejectedValueOnce(new Error('offline'));
    await wrapper.setProps({ endDate: '2026-09-01' }); await flushPromises();
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="daily-pattern-summary"]').exists()).toBe(false);
    vi.mocked(marketDataApi.dailyBars).mockResolvedValueOnce({ ...result, items: [] });
    await wrapper.findAll('button').find(button => button.text() === '重试')!.trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('暂无日 K 数据');
    expect(wrapper.find('[data-testid="daily-pattern-summary"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
