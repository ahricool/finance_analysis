import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { expect, it, vi } from 'vitest';
import { quantApi } from '@/api/quant';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import QuantSignalsPage from '../quant/QuantSignalsPage.vue';

vi.mock('@/api/quant', () => ({ quantApi: { signals: vi.fn() } }));

it('renders realized-return columns including signed percentages and missing values', async () => {
  vi.mocked(quantApi.signals).mockResolvedValue({
    items: [{ id: 1, code: 'AAPL.US', return3D: 0.0321, return5D: -0.0142, returnSince: null }],
  } as never);
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/research/quant/signals', component: QuantSignalsPage },
  ] });
  await router.push('/research/quant/signals');
  await router.isReady();
  const wrapper = mount(QuantSignalsPage, { global: { plugins: [router] } });
  await flushPromises();
  const headings = wrapper.findAll('th').map((cell) => cell.text());
  expect(headings).toEqual(expect.arrayContaining(['3D收益', '5D收益', '至今收益']));
  const cells = wrapper.findAll('tbody td').map((cell) => cell.text());
  expect(cells).toEqual(expect.arrayContaining(['+3.21%', '-1.42%', '--']));
});

it('opens quant evidence in place with its returned snapshot date and resets on market navigation', async () => {
  vi.mocked(quantApi.signals).mockResolvedValue({ tradeDate: '2026-09-21', items: [{ id: 1, code: 'AAPL.US', name: 'Apple', tradeDate: '2026-09-21' }] } as never);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/research/quant/signals', component: QuantSignalsPage }] });
  await router.push('/research/quant/signals?market=US'); await router.isReady();
  const wrapper = mount(QuantSignalsPage, { global: { plugins: [router], stubs: { StockDetailDialog: true } } });
  await flushPromises(); await wrapper.get('tbody button').trigger('click');
  const dialog = wrapper.getComponent(StockDetailDialog);
  expect(dialog.props('open')).toBe(true);
  expect(dialog.props('initialTab')).toBe('overview');
  await wrapper.get('tbody tr').trigger('click');
  expect(dialog.props('initialTab')).toBe('quant');
  expect(dialog.props('context')).toEqual({ tradeDate: '2026-09-21', view: 'official' });
  expect(router.currentRoute.value.fullPath).toBe('/research/quant/signals?market=US');
  dialog.vm.$emit('update:open', false); await flushPromises();
  expect(dialog.props('open')).toBe(false);
  await wrapper.get('tbody button').trigger('click'); expect(dialog.props('open')).toBe(true);
  await router.push('/research/quant/signals?market=CN'); await flushPromises();
  expect(dialog.props('open')).toBe(false); expect(dialog.props('stock')).toBeNull();
  wrapper.unmount();
});
