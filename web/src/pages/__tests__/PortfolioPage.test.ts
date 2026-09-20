import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import HoldingsPage from '../market/HoldingsPage.vue';

const mocks = vi.hoisted(() => ({
  summary: vi.fn(),
  buy: vi.fn(),
  sell: vi.fn(),
  deposit: vi.fn(),
  withdraw: vi.fn(),
  operations: vi.fn(),
  markers: vi.fn(),
  updatePosition: vi.fn(),
  source: vi.fn(),
  connect: vi.fn(),
  disconnect: vi.fn(),
  sync: vi.fn(),
  snapshot: vi.fn(),
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
    deposit: mocks.deposit,
    withdraw: mocks.withdraw,
    operations: mocks.operations,
    markers: mocks.markers,
    updatePosition: mocks.updatePosition,
    source: mocks.source,
    connect: mocks.connect,
    disconnect: mocks.disconnect,
    sync: mocks.sync,
    snapshot: mocks.snapshot,
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
    mocks.summary.mockResolvedValue(summary);
    mocks.positions.mockResolvedValue([{ symbol: '600519.SH', action: 'HOLD', profitStage: 'A', activeStop: '9.6' }]);
    mocks.source.mockResolvedValue({ authStatus: 'DISCONNECTED', syncStatus: 'IDLE' });
    mocks.deposit.mockResolvedValue({});
    mocks.buy.mockResolvedValue({});
    mocks.operations.mockResolvedValue([]);
    mocks.markers.mockResolvedValue([]);
    mocks.updatePosition.mockResolvedValue({ ...summary.positions[0], tradeEngineEnabled: false });
  });
  afterEach(() => wrapper?.unmount());

  it('shows DB portfolio totals and lets the user deposit then buy', async () => {
    await mountPage();
    expect(wrapper.get('[data-testid="cash"]').text()).toContain('90,000');
    expect(wrapper.get('[data-testid="total-asset"]').text()).toContain('100,000');
    expect(wrapper.text()).toContain('600519.SH');
    await wrapper.get('[data-testid="action-deposit"]').trigger('click');
    await wrapper.get('[data-testid="form-amount"]').setValue('100000');
    await wrapper.get('[data-testid="form-submit"]').trigger('click');
    await flushPromises();
    expect(mocks.deposit).toHaveBeenCalledWith({ accountId: 1, amount: '100000' });
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
