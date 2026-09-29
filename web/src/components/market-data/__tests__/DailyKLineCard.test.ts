import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { stocksApi } from '@/api/stocks';
import DailyKLineCard from '../DailyKLineCard.vue';
import MarketKLineChart from '../MarketKLineChart.vue';
import { marketDataApi, type DailyBarsResponse } from '@/api/marketData';
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
