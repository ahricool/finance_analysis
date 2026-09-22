import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { expect, it, vi } from 'vitest';
import { quantApi } from '@/api/quant';
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
