import { describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { ref } from 'vue';
import StockStrategiesPage from '../StockStrategiesPage.vue';
import { stockStrategiesApi as api, type Overview } from '@/api/stockStrategies';

vi.mock('@/api/stockStrategies', () => ({ stockStrategiesApi: { overview: vi.fn(), detail: vi.fn(), run: vi.fn() } }));
vi.mock('@/composables/useAuth', () => ({ useAuth: () => ({ currentUser: ref({ role: 'user' }) }) }));
function fixture(market: 'CN' | 'US'): Overview {
  return { market, items: [{ strategy: { key: 'ma_dd30', name: `${market}测试策略`, slots: 1, atr: 0, version: '1' },
    latest: { tradeDate: '2026-10-19', dailyReturn: .01, totalReturn: .02, cagr: null, maxDrawdown: -.03, exposure: 1 },
    lastRun: { status: 'failed', tradeDate: '2026-10-20', reason: '等待缺失输入' }, status: 'failed' }] } as Overview;
}
async function setup() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/strategies', name: 'strategies', component: StockStrategiesPage },
    { path: '/strategies/:strategyKey', name: 'strategy-detail', component: StockStrategiesPage },
  ] });
  await router.push('/strategies?market=US'); await router.isReady();
  const wrapper = mount(StockStrategiesPage, { global: { plugins: [router] } });
  return { router, wrapper };
}

describe('stock strategy page', () => {
  it('shows failed date separately from the last successful return and preserves market in links', async () => {
    vi.mocked(api.overview).mockResolvedValue(fixture('US'));
    const { wrapper } = await setup(); await flushPromises();
    expect(wrapper.text()).toContain('运行失败');
    expect(wrapper.text()).toContain('2026-10-19');
    expect(wrapper.text()).toContain('2026-10-20：等待缺失输入');
    expect(wrapper.text()).toContain('+1.00%');
    expect(wrapper.find('a[href="/strategies/ma_dd30?market=US"]').exists()).toBe(true);
    expect(wrapper.text()).not.toContain('检查本市场');
    wrapper.unmount();
  });
  it('rejects old market responses after a fast market switch', async () => {
    let oldResolve: (r: Overview) => void = () => {};
    vi.mocked(api.overview).mockImplementation(market => market === 'US'
      ? new Promise(resolve => { oldResolve = resolve; }) : Promise.resolve(fixture('CN')));
    const { router, wrapper } = await setup();
    await router.push('/strategies?market=CN'); await flushPromises();
    oldResolve(fixture('US')); await flushPromises();
    expect(wrapper.text()).toContain('CN测试策略');
    expect(wrapper.text()).not.toContain('US测试策略');
    wrapper.unmount();
  });
});
