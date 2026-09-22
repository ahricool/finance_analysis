import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StockAutocomplete from '@/components/StockAutocomplete/StockAutocomplete.vue';
import HoldingsPage from '../market/HoldingsPage.vue';

const mocks = vi.hoisted(() => ({
  summary: vi.fn(),
  buy: vi.fn(),
  sell: vi.fn(),
  setCash: vi.fn(),
  operations: vi.fn(),
  markers: vi.fn(),
  updatePosition: vi.fn(),
  positions: vi.fn(),
  signals: vi.fn(),
  strategies: vi.fn(),
  run: vi.fn(),
}));

vi.mock('@/api/holdings', () => ({
  holdingsApi: {
    summary: mocks.summary,
    buy: mocks.buy,
    sell: mocks.sell,
    setCash: mocks.setCash,
    operations: mocks.operations,
    markers: mocks.markers,
    updatePosition: mocks.updatePosition,
  },
  tradeEngineApi: {
    positions: mocks.positions,
    signals: mocks.signals,
    strategies: mocks.strategies,
    run: mocks.run,
  },
}));

const summary = {
  market: 'CN',
  accounts: [{ id: 1, name: 'A股账户', market: 'CN', cash: '90000', currency: 'CNY' }],
  cash: '90000',
  marketValue: '10000',
  totalAsset: '100000',
  grossExposure: '0.1',
  positions: [
    {
      id: 11,
      accountId: 1,
      market: 'CN',
      symbol: '600519.SH',
      assetType: 'STOCK',
      quantity: '1000',
      averageCost: '10',
      currentPrice: '12',
      marketValue: '12000',
      weight: '0.12',
      unrealizedPnl: '2000',
      tradeEngineEnabled: true,
    },
  ],
};

let wrapper: VueWrapper;

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/market/holdings', component: HoldingsPage }],
  });
  await router.push('/market/holdings');
  await router.isReady();
  wrapper = mount(HoldingsPage, {
    global: {
      plugins: [createPinia(), router],
      stubs: {
        DailyKLineCard: true,
        StockAutocomplete: true,
        Dialog: { props: ['open'], template: '<div v-if="open"><slot /></div>' },
        DialogContent: { template: '<div><slot /></div>' },
        DialogHeader: { template: '<div><slot /></div>' },
        DialogTitle: { template: '<div><slot /></div>' },
        DialogDescription: { template: '<div><slot /></div>' },
        DialogFooter: { template: '<div><slot /></div>' },
      },
    },
  });
  await flushPromises();
}

describe('HoldingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.summary.mockResolvedValue(summary);
    mocks.positions.mockResolvedValue([{ symbol: '600519.SH', action: 'HOLD', profitStage: 'A', activeStop: '9.6' }]);
    mocks.setCash.mockResolvedValue({});
    mocks.buy.mockResolvedValue({});
    mocks.operations.mockResolvedValue([]);
    mocks.markers.mockResolvedValue([]);
    mocks.updatePosition.mockResolvedValue({ ...summary.positions[0], tradeEngineEnabled: false });
  });
  afterEach(() => wrapper?.unmount());

  it('shows totals and replaces cash with an independently entered balance', async () => {
    await mountPage();
    expect(wrapper.get('[data-testid="cash"]').text()).toContain('90,000');
    expect(wrapper.get('[data-testid="total-asset"]').text()).toContain('100,000');
    expect(wrapper.text()).toContain('600519.SH');
    await wrapper.get('[data-testid="action-cash"]').trigger('click');
    expect((wrapper.get('[data-testid="form-amount"]').element as HTMLInputElement).value).toBe('90000');
    expect(wrapper.text()).not.toMatch(/入金|出金/);
    await wrapper.get('[data-testid="form-amount"]').setValue('100000');
    await wrapper.get('[data-testid="form-submit"]').trigger('click');
    await flushPromises();
    expect(mocks.setCash).toHaveBeenCalledWith({ accountId: 1, amount: '100000' });
  });

  it('requires a search selection and submits canonical code and instrument type', async () => {
    await mountPage();
    await wrapper.get('[data-testid="action-buy"]').trigger('click');
    expect(wrapper.get('[data-testid="form-submit"]').attributes('disabled')).toBeDefined();
    const search = wrapper.getComponent(StockAutocomplete);
    search.vm.$emit('update:modelValue', '510300');
    search.vm.$emit('submit', '510300.SH', '沪深300ETF', 'autocomplete', 'CN', 'etf');
    await flushPromises();
    await wrapper.get('[data-testid="form-quantity"]').setValue('100');
    await wrapper.get('[data-testid="form-price"]').setValue('4');
    await wrapper.get('[data-testid="form-submit"]').trigger('click');
    await flushPromises();
    expect(mocks.buy).toHaveBeenCalledWith({
      accountId: 1, symbol: '510300.SH', assetType: 'ETF', quantity: '100', price: '4',
    });
    expect(mocks.setCash).not.toHaveBeenCalled();
  });

  it('invalidates a selection on edits and rejects manual, other market and index selections', async () => {
    await mountPage();
    await wrapper.get('[data-testid="action-buy"]').trigger('click');
    const search = wrapper.getComponent(StockAutocomplete);
    search.vm.$emit('submit', '600519.SH', '', 'autocomplete', 'CN', 'stock');
    await flushPromises();
    expect(wrapper.get('[data-testid="form-submit"]').attributes('disabled')).toBeUndefined();
    search.vm.$emit('update:modelValue', '600');
    await flushPromises();
    expect(wrapper.get('[data-testid="form-submit"]').attributes('disabled')).toBeDefined();
    for (const args of [
      ['600519.SH', '', 'manual'],
      ['AAPL.US', '', 'autocomplete', 'US', 'stock'],
      ['000001.SH', '', 'autocomplete', 'CN', 'index'],
    ]) {
      search.vm.$emit('submit', ...args);
      await flushPromises();
      expect(wrapper.get('[data-testid="form-submit"]').attributes('disabled')).toBeDefined();
    }
    expect(mocks.buy).not.toHaveBeenCalled();
  });

  it('toggles trade engine from the position detail', async () => {
    await mountPage();
    await wrapper.get('button.text-left').trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('交易提醒');
    await wrapper.get('[data-testid="trade-engine-enabled"]').setValue(false);
    await flushPromises();
    expect(mocks.updatePosition).toHaveBeenCalledWith(11, { tradeEngineEnabled: false });
  });
});
