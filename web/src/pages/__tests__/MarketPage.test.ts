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
    ],
  });
  await router.push(path);
  await router.isReady();
  return mount(MarketPage, { global: { plugins: [router] } });
}

describe('MarketPage', () => {
  it('renders four desktop and mobile tabs with the current tab selected', async () => {
    const wrapper = await mountMarket('/market/signals');

    expect(wrapper.text()).toContain('管理自选股、持仓股，查看历史信号并执行策略回测。');
    expect(wrapper.get('[data-testid="market-desktop-nav"]').classes()).toContain('lg:block');
    expect(wrapper.get('[data-testid="market-mobile-nav"]').classes()).toContain('lg:hidden');
    expect(wrapper.findAll('a[href="/market/watch-list"]')).toHaveLength(2);
    expect(wrapper.findAll('a[href="/market/holdings"]')).toHaveLength(2);
    const signalLinks = wrapper.findAll('a[href="/market/signals"]');
    expect(signalLinks).toHaveLength(2);
    expect(signalLinks.every((link) => link.classes().includes('text-primary'))).toBe(true);
    expect(wrapper.text()).toContain('信号内容');
  });

  it('keeps the backtest tab active on a run detail route', async () => {
    const wrapper = await mountMarket('/market/backtests/123');
    const links = wrapper.findAll('a[href="/market/backtests"]');
    expect(links).toHaveLength(2);
    expect(links.every((link) => link.classes().includes('text-primary'))).toBe(true);
  });
});
