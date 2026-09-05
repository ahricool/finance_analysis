import { mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it } from 'vitest';
import MarketPage from '../MarketPage.vue';

async function mountMarket(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/market/watch-list', component: { template: '<div>自选内容</div>' } },
      { path: '/market/holdings', component: { template: '<div>持仓内容</div>' } },
    ],
  });
  await router.push(path);
  await router.isReady();
  return mount(MarketPage, { global: { plugins: [router] } });
}

describe('MarketPage', () => {
  it('renders market tabs with the current tab selected', async () => {
    const wrapper = await mountMarket('/market/holdings');

    expect(wrapper.text()).toContain('管理自选股和投资组合。');
    expect(wrapper.get('[data-testid="module-tabs"]').attributes('aria-label')).toBe('市场页面导航');
    expect(wrapper.get('[data-testid="module-tabs"]').findAll('a')).toHaveLength(2);
    expect(wrapper.findAll('a[href="/market/watch-list"]')).toHaveLength(1);
    const holdingLinks = wrapper.findAll('a[href="/market/holdings"]');
    expect(holdingLinks).toHaveLength(1);
    expect(holdingLinks[0]?.attributes('data-state')).toBe('active');
    expect(wrapper.text()).toContain('持仓内容');
    expect(wrapper.text()).not.toContain('策略回测');
    expect(wrapper.text()).not.toContain('量化研究');
  });
});
