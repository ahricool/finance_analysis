import { createPinia, setActivePinia } from 'pinia';
import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, expect, it, vi } from 'vitest';
import QuantDetailPanel from '@/components/stocks/detail/QuantDetailPanel.vue';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import QuantSignalDetailPage from '../quant/QuantSignalDetailPage.vue';
import { marketDataApi } from '@/api/marketData';
vi.mock('@/api/marketData', () => ({ marketDataApi: { dailyBars: vi.fn().mockRejectedValue(new Error('offline')) } }));
vi.mock('@/api/quant', () => ({ quantApi: {
  signal: vi.fn().mockResolvedValue({ code: 'AAPL.US', name: 'Apple', tradeDate: '2026-08-21', reasons: ['历史原因'], components: {} }),
  signalHistory: vi.fn().mockResolvedValue([]),
} }));
beforeEach(() => { localStorage.clear(); setActivePinia(createPinia()); });

it('keeps quant research independent of general market chart requests', async () => {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/research/quant/signals/:code', component: QuantSignalDetailPage },
  ] });
  await router.push('/research/quant/signals/AAPL.US?market=US&tradeDate=2026-08-21');
  await router.isReady();
  const wrapper = mount(QuantDetailPanel, { props: { symbol: 'AAPL.US', market: 'US', context: { tradeDate: '2026-08-21' } }, global: { plugins: [router] } });
  await flushPromises();
  expect(marketDataApi.dailyBars).not.toHaveBeenCalled();
  expect(wrapper.text()).toContain('历史原因');
  wrapper.unmount();
});

it('keeps direct quant links compatible and closes to the ranking with market and date intact', async () => {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/research/quant/signals/:code', component: QuantSignalDetailPage },
    { path: '/research/quant/signals', component: { template: '<div>排名</div>' } },
  ] });
  await router.push('/research/quant/signals/600001.SH?market=CN&tradeDate=2026-08-21');
  await router.isReady();
  const wrapper = mount(QuantSignalDetailPage, { global: { plugins: [router], stubs: { StockDetailDialog: true } } });
  const dialog = wrapper.getComponent(StockDetailDialog);
  expect(dialog.props('stock')).toMatchObject({ code: '600001.SH', marketType: 'CN' });
  expect(dialog.props('initialTab')).toBe('quant');
  expect(dialog.props('context')).toEqual({ tradeDate: '2026-08-21', view: 'official' });
  dialog.vm.$emit('update:open', false);
  await flushPromises();
  expect(router.currentRoute.value.path).toBe('/research/quant/signals');
  expect(router.currentRoute.value.query).toMatchObject({ market: 'CN', tradeDate: '2026-08-21' });
  wrapper.unmount();
});
