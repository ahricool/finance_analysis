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
  it('renders market-style responsive secondary navigation with the switcher below the subtitle', async () => {
    const wrapper = await mountQuant('/market/quant');

    expect(wrapper.get('h1').text()).toBe('量化研究');
    expect(wrapper.get('[data-testid="quant-mobile-nav"]').classes()).toContain('lg:hidden');
    expect(wrapper.get('[data-testid="quant-desktop-nav"]').classes()).toContain('lg:block');
    expect(wrapper.get('header').find('[data-testid="quant-market-switcher"]').exists()).toBe(true);
    expect(wrapper.get('header').find('[data-testid="quant-scope-description"]').exists()).toBe(true);
    expect(wrapper.get('a[href="/market/quant?market=US"]').classes()).toContain('text-primary');
    expect(wrapper.get('a[href="/market/quant/datasets?market=US"]').text()).toBe('数据集');
    expect(wrapper.text()).toContain('量化总览');
  });

  it('keeps a section active on a detail route', async () => {
    const wrapper = await mountQuant('/market/quant/signals/NVDA.US');

    expect(wrapper.get('a[href="/market/quant/signals?market=US"]').classes()).toContain('text-primary');
    expect(wrapper.get('a[href="/market/quant?market=US"]').classes()).not.toContain('text-primary');
    expect(wrapper.text()).toContain('选股详情');
  });
});
