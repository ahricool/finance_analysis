import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import QuantPage from '../QuantPage.vue';
import QuantDashboardPage from '../quant/QuantDashboardPage.vue';
import { quantApi } from '@/api/quant';

vi.mock('@/api/quant', () => ({
  quantApi: {
    capabilities: vi.fn(),
    marketRegime: vi.fn(),
    marketRegimeHistory: vi.fn(),
    sectors: vi.fn(),
    signals: vi.fn(),
  },
}));

const capability = {
  status: 'degraded', market: 'US', pythonVersion: '3.13', priceModes: ['raw'], markets: { US: 'available', CN: 'available' },
  qlib: { status: 'configured', version: '0.9.7', execution: 'celery_queue', reason: null },
  models: { status: 'unavailable', required: {} }, adjustedPrices: { status: 'unavailable', reason: 'raw' }, warnings: [],
};

async function mountMarket(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/market/quant', component: QuantPage, children: [{ path: '', component: QuantDashboardPage }] }],
  });
  await router.push(path);
  await router.isReady();
  const wrapper = mount(QuantPage, { global: { plugins: [router] } });
  return { wrapper, router };
}

describe('quant market context', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(quantApi.capabilities).mockResolvedValue(capability as never);
    vi.mocked(quantApi.marketRegime).mockRejectedValue({ response: { status: 404, data: { detail: 'missing' } } });
    vi.mocked(quantApi.marketRegimeHistory).mockResolvedValue([]);
    vi.mocked(quantApi.sectors).mockResolvedValue([]);
    vi.mocked(quantApi.signals).mockResolvedValue({ tradeDate: null, market: 'US', universe: 'us_sp500_watchlist', marketRegime: null, maxEquityExposure: null, items: [] });
  });

  it('defaults to US and stores CN selection in the route query', async () => {
    const { wrapper, router } = await mountMarket('/market/quant');
    await flushPromises();
    const controls = wrapper.get('[data-testid="quant-market-switcher"]');
    expect(controls.attributes('role')).toBe('radiogroup');
    expect(controls.get('button[aria-checked="true"]').text()).toBe('美股');

    await controls.findAll('button')[1].trigger('click');
    await flushPromises();

    expect(router.currentRoute.value.query.market).toBe('CN');
    expect(controls.get('button[aria-checked="true"]').text()).toBe('A股');
    expect(controls.classes()).toContain('min-w-[132px]');
    expect(quantApi.signals).toHaveBeenLastCalledWith('CN');
  });

  it('honors market=CN on refresh and never restores a late US ranking', async () => {
    let resolveUs!: (value: Awaited<ReturnType<typeof quantApi.signals>>) => void;
    vi.mocked(quantApi.signals).mockImplementation((market) => {
      if (market === 'US') return new Promise((resolve) => { resolveUs = resolve; });
      return Promise.resolve({ tradeDate: null, market: 'CN', universe: 'cn_csi300_watchlist', marketRegime: null, maxEquityExposure: null, items: [] });
    });
    const { wrapper, router } = await mountMarket('/market/quant?market=US');
    await flushPromises();
    await router.push('/market/quant?market=CN');
    await flushPromises();
    resolveUs({
      tradeDate: '2026-07-17', market: 'US', universe: 'us_sp500_watchlist', marketRegime: 'risk_on', maxEquityExposure: 0.8,
      items: [{ id: 1, market: 'US', tradeDate: '2026-07-17', code: 'AAPL.US' } as never],
    });
    await flushPromises();

    expect(wrapper.text()).toContain('A股模型尚未就绪');
    expect(wrapper.text()).not.toContain('AAPL.US');
    expect(quantApi.signals).toHaveBeenCalledWith('CN');
  });
});
