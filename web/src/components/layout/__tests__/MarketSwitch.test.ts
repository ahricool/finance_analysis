import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it } from 'vitest';
import { createMemoryHistory, createRouter } from 'vue-router';
import MarketSwitch from '../MarketSwitch.vue';
import { useMarketStore } from '@/stores/marketStore';
import { useStockDetail } from '@/composables/useStockDetail';

beforeEach(() => { localStorage.clear(); setActivePinia(createPinia()); useStockDetail().close(); });
async function setup(path: string) {
  const component = { template: '<div />' };
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/timeline', component, meta: { marketScope: 'selectable' } },
    { path: '/profile', component },
    { path: '/industry', component, meta: { marketScope: 'CN' } },
    { path: '/options', component, meta: { marketScope: 'US' } },
    { path: '/strategies', component, meta: { marketScope: 'selectable' } },
    { path: '/strategies/:key', name: 'strategy-detail', component, meta: { marketScope: 'selectable' } },
    { path: '/research/quant/signals', component, meta: { marketScope: 'selectable' } },
    { path: '/research/quant/signals/:code', name: 'research-quant-signal-detail', component, meta: { marketScope: 'selectable' } },
    { path: '/research/quant/models', component, meta: { marketScope: 'selectable' } },
    { path: '/research/quant/models/:id', name: 'research-quant-model-run', component, meta: { marketScope: 'selectable' } },
  ] });
  await router.push(path);
  const wrapper = mount(MarketSwitch, { global: { plugins: [router] } });
  return { router, wrapper, control: wrapper.get('[role="switch"]') };
}

describe('global market switch', () => {
  it('updates the URL, clears market-specific context, persists selection and closes shared detail', async () => {
    const { router, wrapper, control } = await setup('/timeline?market=CN&tradeDate=2026-10-29&symbol=600000.SH&keep=yes#feed');
    useStockDetail().open({ code: '600000.SH', name: '浦发银行', marketType: 'CN' });
    await control.trigger('click'); await flushPromises();
    expect(control.attributes('aria-checked')).toBe('true');
    expect(router.currentRoute.value.query).toEqual({ market: 'US', keep: 'yes' });
    expect(router.currentRoute.value.hash).toBe('#feed');
    expect(localStorage.getItem('selected_market')).toBe('US');
    expect(useStockDetail().selection.value).toBeNull();
    wrapper.unmount();
  });

  it('disables on unrelated and single-market pages and restores the preference on return', async () => {
    useMarketStore().setMarket('US');
    const { router, wrapper, control } = await setup('/profile');
    expect(control.attributes('disabled')).toBeDefined();
    await router.push('/industry');
    expect(control.attributes('aria-checked')).toBe('false');
    await control.trigger('click');
    expect(useMarketStore().market).toBe('US');
    await router.push('/options');
    expect(control.attributes('aria-checked')).toBe('true');
    expect(control.attributes('disabled')).toBeDefined();
    await router.push('/timeline');
    expect(control.attributes('disabled')).toBeUndefined();
    expect(control.attributes('aria-checked')).toBe('true');
    wrapper.unmount();
  });

  it.each([
    ['/strategies/cn-only?market=CN', '/strategies'],
    ['/research/quant/signals/600000.SH?market=CN', '/research/quant/signals'],
    ['/research/quant/models/123?market=CN', '/research/quant/models'],
  ])('leaves the old detail identifier when changing market from %s', async (path, target) => {
    const { router, wrapper, control } = await setup(path);
    await control.trigger('click'); await flushPromises();
    expect(router.currentRoute.value.path).toBe(target);
    expect(router.currentRoute.value.query.market).toBe('US');
    wrapper.unmount();
  });

  it('does not save a market when navigation is rejected', async () => {
    const { router, wrapper, control } = await setup('/timeline?market=CN');
    router.beforeEach(() => false);
    await control.trigger('click'); await flushPromises();
    expect(useMarketStore().market).toBe('CN');
    expect(control.attributes('aria-checked')).toBe('false');
    wrapper.unmount();
  });
});
