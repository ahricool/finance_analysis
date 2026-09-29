import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { quantApi } from '@/api/quant';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import QuantPage from '../QuantPage.vue';

vi.mock('@/api/quant', () => ({ quantApi: { dates: vi.fn() } }));

beforeEach(() => {
  vi.mocked(quantApi.dates).mockReset().mockResolvedValue({ items: ['2026-09-25', '2026-09-23'] });
});

async function mountQuant(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/research/quant',
        component: QuantPage,
        children: [
          { path: '', component: { template: '<div>量化总览</div>' } },
          { path: 'portfolios', component: { template: '<div>目标组合</div>' } },
          { path: 'signals/:code', component: { template: '<div>选股详情</div>' } },
        ],
      },
    ],
  });
  await router.push(path);
  await router.isReady();
  return mount(QuantPage, { global: { plugins: [router] } });
}

describe('QuantPage', () => {
  it('renders responsive secondary navigation with the market switcher alongside the tabs', async () => {
    const wrapper = await mountQuant('/research/quant');

    expect(wrapper.get('[data-testid="module-tabs"]').attributes('aria-label')).toBe('量化研究导航');
    expect(wrapper.find('[data-testid="quant-market-switcher"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="quant-scope-description"]').text()).toContain('当前范围');
    expect(wrapper.get('a[href="/research/quant?market=US"]').attributes('data-state')).toBe('active');
    expect(wrapper.get('a[href="/research/quant/datasets?market=US"]').text()).toBe('数据集');
    expect(wrapper.text()).toContain('量化总览');
  });

  it('keeps a section active on a detail route', async () => {
    const wrapper = await mountQuant('/research/quant/signals/NVDA.US');

    expect(wrapper.get('a[href="/research/quant/signals?market=US"]').attributes('data-state')).toBe('active');
    expect(wrapper.get('a[href="/research/quant?market=US"]').attributes('data-state')).toBe('inactive');
    expect(wrapper.text()).toContain('选股详情');
  });
});

it('restricts selection to persisted dates and preserves clearing to latest', async () => {
  const wrapper = await mountQuant('/research/quant?market=CN');
  await flushPromises();
  const picker = wrapper.getComponent(AppDatePicker);
  expect(quantApi.dates).toHaveBeenCalledWith('CN', 'dashboard', undefined);
  expect(picker.props('availableDates')).toEqual(['2026-09-25', '2026-09-23']);
  picker.vm.$emit('update:modelValue', '2026-09-24');
  await flushPromises();
  expect(wrapper.vm.$route.query.tradeDate).toBeUndefined();
  picker.vm.$emit('update:modelValue', '2026-09-23');
  await flushPromises();
  expect(wrapper.vm.$route.query.tradeDate).toBe('2026-09-23');
  picker.vm.$emit('update:modelValue', '');
  await flushPromises();
  expect(wrapper.vm.$route.query.tradeDate).toBeUndefined();
});

it('scopes detail dates by security and portfolio dates by market', async () => {
  const wrapper = await mountQuant('/research/quant/signals/NVDA.US');
  await flushPromises();
  expect(quantApi.dates).toHaveBeenCalledWith('US', 'signals', 'NVDA.US');
  await wrapper.vm.$router.push('/research/quant/portfolios?market=CN');
  await flushPromises();
  expect(quantApi.dates).toHaveBeenLastCalledWith('CN', 'portfolios', undefined);
});

it('disables empty and failed date lists', async () => {
  vi.mocked(quantApi.dates).mockResolvedValueOnce({ items: [] });
  const wrapper = await mountQuant('/research/quant');
  await flushPromises();
  expect(wrapper.getComponent(AppDatePicker).props('disabled')).toBe(true);
  vi.mocked(quantApi.dates).mockRejectedValueOnce(new Error('dates unavailable'));
  await wrapper.vm.$router.push('/research/quant?market=CN');
  await flushPromises();
  expect(wrapper.getComponent(AppDatePicker).props('disabled')).toBe(true);
});

it('clears old dates while loading and ignores stale market responses', async () => {
  let resolveOld!: (value: { items: string[] }) => void;
  vi.mocked(quantApi.dates).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  const wrapper = await mountQuant('/research/quant');
  expect(wrapper.getComponent(AppDatePicker).props('disabled')).toBe(true);
  await wrapper.vm.$router.push('/research/quant?market=CN');
  await flushPromises();
  resolveOld({ items: ['2020-01-01'] });
  await flushPromises();
  expect(wrapper.getComponent(AppDatePicker).props('availableDates')).toEqual(['2026-09-25', '2026-09-23']);
});
