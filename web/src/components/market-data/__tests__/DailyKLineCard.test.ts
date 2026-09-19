import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DailyKLineCard from '../DailyKLineCard.vue';
import MarketKLineChart from '../MarketKLineChart.vue';
import { marketDataApi, type DailyBarsResponse } from '@/api/marketData';
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
    expect(wrapper.getComponent(MarketKLineChart).props('pricePrecision')).toBe(3);
    expect(wrapper.getComponent(MarketKLineChart).props('bars')[0]).toEqual({ timestamp: Date.parse('2026-09-18T00:00:00Z'),
      open: 100, high: 105, low: 1.237, close: 103, volume: 100, turnover: 1000 });
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
