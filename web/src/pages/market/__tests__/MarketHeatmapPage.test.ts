import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createRouter, createMemoryHistory } from 'vue-router';
import { createPinia } from 'pinia';
import { getMarketHeatmap, type HeatmapResponse } from '@/api/marketHeatmap';
import MarketHeatmapPage from '../MarketHeatmapPage.vue';
import { useStockDetail } from '@/composables/useStockDetail';

vi.mock('@/api/marketHeatmap', () => ({ getMarketHeatmap: vi.fn() }));
vi.mock('@/components/market-heatmap/HeatmapChart.vue', () => ({ default: { name: 'HeatmapChart', props: ['snapshot', 'search', 'groupCode'], emits: ['select'], template: '<div>{{ snapshot.market }}</div>' } }));
const ready = (market: 'CN' | 'US' = 'CN'): HeatmapResponse => ({ status: 'ready', snapshot: {
  market, source: 'test', generatedAt: '2026-10-23T02:00:00Z', dataAsOf: null, dataLatestAt: null,
  classificationObservedAt: null, minMarketCap: market === 'CN' ? 1e10 : 2e9, refreshSeconds: 900,
  excludedCount: 0, unclassifiedCount: 0, items: [{ code: market === 'CN' ? '600519.SH' : 'AAPL.US',
    name: 'Example', marketCap: 1e12, price: 10, changePct: 1, groupCode: 'test', groupName: '行业', quoteTime: null }],
} });
async function setup() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/market/heatmap', component: MarketHeatmapPage }] });
  await router.push('/market/heatmap'); await router.isReady();
  const wrapper = mount(MarketHeatmapPage, { global: { plugins: [router, createPinia()] } });
  await flushPromises();
  return { router, wrapper };
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(getMarketHeatmap).mockResolvedValue(ready()); });
afterEach(() => { vi.useRealTimers(); useStockDetail().close(); });
describe('market heatmap page', () => {
  it('uses the App detail host and only sets one shared selection', async () => {
    const { wrapper } = await setup();
    expect(wrapper.findComponent({ name: 'StockDetailHost' }).exists()).toBe(false);
    wrapper.getComponent({ name: 'HeatmapChart' }).vm.$emit('select', ready().snapshot!.items[0]);
    expect(useStockDetail().selection.value?.stock.code).toBe('600519.SH');
    wrapper.unmount();
  });
  it('filters locally, displays no results, and resets filters on market changes', async () => {
    const { wrapper } = await setup();
    await wrapper.get('[aria-label="搜索热力图股票"]').setValue('missing');
    expect(wrapper.text()).toContain('没有匹配的股票');
    expect(getMarketHeatmap).toHaveBeenCalledTimes(1);
    vi.mocked(getMarketHeatmap).mockResolvedValue(ready('US'));
    await wrapper.get('[data-testid="heatmap-market-US"]').trigger('click'); await flushPromises();
    expect((wrapper.get('[aria-label="搜索热力图股票"]').element as HTMLInputElement).value).toBe('');
    expect(wrapper.find('[data-testid="heatmap-chart"]').exists()).toBe(true);
    wrapper.unmount();
  });
  it('switches markets, clears the old market and reads only cached snapshots', async () => {
    const { wrapper } = await setup();
    expect(wrapper.text()).toContain('100.0亿元');
    vi.mocked(getMarketHeatmap).mockResolvedValue(ready('US'));
    await wrapper.get('[data-testid="heatmap-market-US"]').trigger('click'); await flushPromises();
    expect(getMarketHeatmap).toHaveBeenLastCalledWith('US');
    expect(wrapper.text()).toContain('20.0亿美元');
    wrapper.unmount();
  });
  it('shows empty and stale states without triggering generation', async () => {
    vi.mocked(getMarketHeatmap).mockResolvedValue({ status: 'empty', snapshot: null });
    const { wrapper } = await setup();
    expect(wrapper.text()).toContain('尚无热力图快照');
    vi.mocked(getMarketHeatmap).mockResolvedValue({ ...ready(), status: 'stale' });
    await wrapper.get('[aria-label="重新读取热力图快照"]').trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('当前显示上次成功快照');
    expect(wrapper.find('[data-testid="heatmap-chart"]').exists()).toBe(true);
    wrapper.unmount();
  });
  it('ignores an older response after switching markets', async () => {
    let resolveOld!: (value: HeatmapResponse) => void;
    vi.mocked(getMarketHeatmap).mockImplementation(market => market === 'CN'
      ? new Promise(resolve => { resolveOld = resolve; }) : Promise.resolve(ready('US')));
    const { wrapper } = await setup();
    await wrapper.get('[data-testid="heatmap-market-US"]').trigger('click'); await flushPromises();
    resolveOld(ready('CN')); await flushPromises();
    expect(wrapper.text()).toContain('20.0亿美元');
    expect(wrapper.text()).not.toContain('100.0亿元');
    wrapper.unmount();
  });
  it('polls every 15 minutes and stops on unmount', async () => {
    vi.useFakeTimers();
    const { wrapper } = await setup();
    expect(getMarketHeatmap).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(900_000);
    expect(getMarketHeatmap).toHaveBeenCalledTimes(2);
    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(900_000);
    expect(getMarketHeatmap).toHaveBeenCalledTimes(2);
  });
});
