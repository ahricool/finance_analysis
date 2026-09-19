import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { expect, it, vi } from 'vitest';
import QuantSignalDetailPage from '../quant/QuantSignalDetailPage.vue';
import { marketDataApi } from '@/api/marketData';
vi.mock('@/api/marketData', () => ({ marketDataApi: { dailyBars: vi.fn().mockRejectedValue(new Error('offline')) } }));
vi.mock('@/api/quant', () => ({ quantApi: {
  signal: vi.fn().mockResolvedValue({ code: 'AAPL.US', name: 'Apple', tradeDate: '2026-08-21', reasons: ['历史原因'], components: {} }),
  signalHistory: vi.fn().mockResolvedValue([]),
} }));
it('bounds daily bars to signal tradeDate and keeps the detail usable on chart failure', async () => {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/research/quant/signals/:code', component: QuantSignalDetailPage },
  ] });
  await router.push('/research/quant/signals/AAPL.US?market=US&tradeDate=2026-08-21');
  await router.isReady();
  const wrapper = mount(QuantSignalDetailPage, { global: { plugins: [router] } });
  await flushPromises();
  expect(marketDataApi.dailyBars).toHaveBeenCalledWith('AAPL.US', '2026-08-21', undefined, expect.any(AbortSignal));
  expect(wrapper.text()).toContain('历史原因');
  expect(wrapper.text()).toContain('重试');
  wrapper.unmount();
});
