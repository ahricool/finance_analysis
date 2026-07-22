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
  it('renders its secondary navigation without the market sidebar', async () => {
    const wrapper = await mountQuant('/market/quant');

    expect(wrapper.get('nav[aria-label="量化研究导航"]').classes()).toContain('flex-wrap');
    expect(wrapper.get('a[href="/market/quant?market=US"]').classes()).toContain('text-primary');
    expect(wrapper.get('a[href="/market/quant/datasets?market=US"]').text()).toBe('数据集');
    expect(wrapper.text()).toContain('量化总览');
    expect(wrapper.find('[data-testid="market-desktop-nav"]').exists()).toBe(false);
  });

  it('keeps a section active on a detail route', async () => {
    const wrapper = await mountQuant('/market/quant/signals/NVDA.US');

    expect(wrapper.get('a[href="/market/quant/signals?market=US"]').classes()).toContain('text-primary');
    expect(wrapper.get('a[href="/market/quant?market=US"]').classes()).not.toContain('text-primary');
    expect(wrapper.text()).toContain('选股详情');
  });
});
