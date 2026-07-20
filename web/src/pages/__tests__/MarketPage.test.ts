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
      { path: '/market/signals', component: { template: '<div>信号内容</div>' } },
    ],
  });
  await router.push(path);
  await router.isReady();
  return mount(MarketPage, { global: { plugins: [router] } });
}

describe('MarketPage', () => {
  it('renders market tabs with the current tab selected', async () => {
    const wrapper = await mountMarket('/market/signals');

    expect(wrapper.text()).toContain('管理自选股、持仓股并查看历史信号。');
    expect(wrapper.get('[data-testid="market-desktop-nav"]').classes()).toContain('lg:block');
    const mobileNav = wrapper.get('[data-testid="market-mobile-nav"]');
    expect(mobileNav.classes()).toContain('lg:hidden');
    expect(mobileNav.classes()).toContain('grid-cols-3');
    expect(mobileNav.classes()).not.toContain('overflow-x-auto');
    expect(wrapper.findAll('a[href="/market/watch-list"]')).toHaveLength(2);
    expect(wrapper.findAll('a[href="/market/holdings"]')).toHaveLength(2);
    const signalLinks = wrapper.findAll('a[href="/market/signals"]');
    expect(signalLinks).toHaveLength(2);
    expect(signalLinks.every((link) => link.classes().includes('text-primary'))).toBe(true);
    expect(wrapper.text()).toContain('信号内容');
    expect(wrapper.text()).not.toContain('策略回测');
    expect(wrapper.text()).not.toContain('量化研究');
  });
});
