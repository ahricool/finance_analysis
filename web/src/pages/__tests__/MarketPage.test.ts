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
      { path: '/market/backtests', component: { template: '<div>回测内容</div>' } },
      { path: '/market/backtests/:runId', component: { template: '<div>回测详情</div>' } },
      { path: '/market/quant', component: { template: '<div>量化内容</div>' } },
      { path: '/market/quant/signals/:code', component: { template: '<div>选股详情</div>' } },
    ],
  });
  await router.push(path);
  await router.isReady();
  return mount(MarketPage, { global: { plugins: [router] } });
}

describe('MarketPage', () => {
  it('renders market tabs with the current tab selected', async () => {
    const wrapper = await mountMarket('/market/signals');

    expect(wrapper.text()).toContain('管理自选股、持仓股，查看历史信号并执行策略回测。');
    expect(wrapper.get('[data-testid="market-desktop-nav"]').classes()).toContain('lg:block');
    const mobileNav = wrapper.get('[data-testid="market-mobile-nav"]');
    expect(mobileNav.classes()).toContain('lg:hidden');
    expect(mobileNav.classes()).toContain('grid-cols-2');
    expect(mobileNav.classes()).toContain('sm:grid-cols-5');
    expect(mobileNav.classes()).not.toContain('overflow-x-auto');
    expect(wrapper.findAll('a[href="/market/watch-list"]')).toHaveLength(2);
    expect(wrapper.findAll('a[href="/market/holdings"]')).toHaveLength(2);
    const signalLinks = wrapper.findAll('a[href="/market/signals"]');
    expect(signalLinks).toHaveLength(2);
    expect(signalLinks.every((link) => link.classes().includes('text-primary'))).toBe(true);
    expect(wrapper.text()).toContain('信号内容');
  });

  it('keeps quant navigation active on a detail route', async () => {
    const wrapper = await mountMarket('/market/quant/signals/NVDA.US');
    const links = wrapper.findAll('a[href="/market/quant"]');
    expect(links.slice(0, 2).every((link) => link.classes().includes('text-primary'))).toBe(true);
    const quantNav = wrapper.get('nav[aria-label="量化研究导航"]');
    expect(quantNav.classes()).toContain('flex-wrap');
    expect(quantNav.classes()).not.toContain('overflow-x-auto');
    expect(wrapper.text()).toContain('选股详情');
  });

  it('keeps the backtest tab active on a run detail route', async () => {
    const wrapper = await mountMarket('/market/backtests/123');
    const links = wrapper.findAll('a[href="/market/backtests"]');
    expect(links).toHaveLength(2);
    expect(links.every((link) => link.classes().includes('text-primary'))).toBe(true);
  });
});
