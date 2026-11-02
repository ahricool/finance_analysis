import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { marketDataApi, type DailyBarsResponse } from '@/api/marketData';
import { setFieldSelect } from '../../../../tests/helpers/fieldSelect';
import OptionStrategyPanel from '../OptionStrategyPanel.vue';
import { OPTION_STRATEGIES } from '@/utils/optionsStrategies/catalog';
vi.mock('@/api/marketData', () => ({ marketDataApi: { dailyBars: vi.fn() } }));
const response: DailyBarsResponse = { symbol: '600519.SH', market: 'CN', interval: '1d', adjustment: 'forward', source: 'test',
  items: Array.from({ length: 21 }, (_, i) => ({ tradeDate: `2026-10-${String(i + 10).padStart(2, '0')}`, open: 100 + i, high: 101 + i, low: 99 + i, close: 100 + i, volume: 1000, amount: null })) };
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(marketDataApi.dailyBars).mockResolvedValue(response); });
describe('OptionStrategyPanel', () => {
  it('defaults to 10-day swing scoring and switches to 5-day short term without another request', async () => {
    const wrapper = mount(OptionStrategyPanel, { props: { symbol: response.symbol, market: 'CN', endDate: '2026-10-30' } }); await flushPromises();
    expect(wrapper.get('[data-testid="option-horizon-swing"]').attributes('aria-pressed')).toBe('true');
    expect(wrapper.text()).toContain('近 10 日涨跌');
    expect(wrapper.text()).toContain('趋势适配分，不是获利概率');
    expect(wrapper.findAll('[data-score]').length).toBe(8);
    const firstScores = wrapper.findAll('[data-score]').map(row => Number(row.attributes('data-score')));
    expect(firstScores).toEqual([...firstScores].sort((a, b) => b - a));
    await wrapper.get('[data-testid="option-horizon-short"]').trigger('click');
    expect(wrapper.text()).toContain('近 5 日涨跌');
    expect(marketDataApi.dailyBars).toHaveBeenCalledTimes(1);
    expect(marketDataApi.dailyBars).toHaveBeenCalledWith(response.symbol, '2026-10-30', expect.any(String), expect.any(AbortSignal)); wrapper.unmount();
  });
  it('searches the full catalog, exposes rich named hints and keeps sorting before pagination', async () => {
    const wrapper = mount(OptionStrategyPanel, { props: { symbol: response.symbol, market: 'CN' } }); await flushPromises();
    expect(wrapper.text()).toContain(`${OPTION_STRATEGIES.length} / ${OPTION_STRATEGIES.length} 种`);
    await wrapper.get('input[aria-label="搜索期权玩法"]').setValue('卖出铁鹰');
    const hint = wrapper.findComponent({ name: 'MetricHint' }); expect(hint.exists()).toBe(true);
    expect(wrapper.get('[data-testid="option-strategy-short-iron-condor"]').text()).toContain('Short Iron Condor');
    expect(wrapper.findAllComponents({ name: 'MetricHint' }).some(component => component.props('label') === '卖出铁鹰'
      && component.props('description').includes('结构：') && component.props('description').includes('IV'))).toBe(true);
    await wrapper.get('input').setValue('');
    await setFieldSelect(wrapper, '[aria-label="玩法排序"]', 'asc');
    const values = wrapper.findAll('[data-score]').map(row => Number(row.attributes('data-score')));
    expect(values).toEqual([...values].sort((a, b) => a - b));
    await setFieldSelect(wrapper, '[aria-label="玩法分类"]', '套利与融资');
    expect(wrapper.text()).toContain('无法由K线趋势评分');
    expect(wrapper.findAll('[data-score]').length).toBe(0); wrapper.unmount();
  });
  it('shows the complete catalog with missing scores when no Kline data exists', async () => {
    vi.mocked(marketDataApi.dailyBars).mockResolvedValue({ ...response, items: [] });
    const wrapper = mount(OptionStrategyPanel, { props: { symbol: response.symbol, market: 'CN' } }); await flushPromises();
    expect(wrapper.text()).toContain('至少需要 11 根有效日K');
    expect(wrapper.findAll('[data-score]').length).toBe(0);
    expect(wrapper.text()).not.toContain('NaN');
    expect(wrapper.text()).not.toContain('0.00%'); wrapper.unmount();
  });
  it('cancels stale symbol/date responses and never mixes two securities', async () => {
    const old = deferred<DailyBarsResponse>(); vi.mocked(marketDataApi.dailyBars).mockReturnValueOnce(old.promise);
    const wrapper = mount(OptionStrategyPanel, { props: { symbol: response.symbol, market: 'CN' } });
    const signal = vi.mocked(marketDataApi.dailyBars).mock.calls[0]![3]!;
    vi.mocked(marketDataApi.dailyBars).mockResolvedValue({ ...response, symbol: 'AAPL.US', market: 'US' });
    await wrapper.setProps({ symbol: 'AAPL.US', market: 'US' }); await flushPromises();
    expect(signal.aborted).toBe(true);
    old.resolve({ ...response, items: [] }); await flushPromises();
    expect(wrapper.text()).toContain('上行趋势'); expect(wrapper.text()).not.toContain('至少需要');
    const last = vi.mocked(marketDataApi.dailyBars).mock.calls.at(-1)![3]!;
    wrapper.unmount(); expect(last.aborted).toBe(true);
  });
});
