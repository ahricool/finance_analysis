import { mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it } from 'vitest';
import QuantPage from '../QuantPage.vue';

async function mountQuant(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/market/quant',
        component: QuantPage,
        children: [
          { path: '', component: { template: '<div>量化总览</div>' } },
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
    const wrapper = await mountQuant('/market/quant');

    expect(wrapper.get('[data-testid="module-tabs"]').attributes('aria-label')).toBe('量化研究导航');
    expect(wrapper.find('[data-testid="quant-market-switcher"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="quant-scope-description"]').text()).toContain('当前范围');
    expect(wrapper.get('a[href="/market/quant?market=US"]').attributes('data-state')).toBe('active');
    expect(wrapper.get('a[href="/market/quant/datasets?market=US"]').text()).toBe('数据集');
    expect(wrapper.text()).toContain('量化总览');
  });

  it('keeps a section active on a detail route', async () => {
    const wrapper = await mountQuant('/market/quant/signals/NVDA.US');

    expect(wrapper.get('a[href="/market/quant/signals?market=US"]').attributes('data-state')).toBe('active');
    expect(wrapper.get('a[href="/market/quant?market=US"]').attributes('data-state')).toBe('inactive');
    expect(wrapper.text()).toContain('选股详情');
  });
});
