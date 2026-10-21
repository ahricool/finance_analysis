import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createOperationId } from '@/utils/operationId';
import StockAutocomplete from '@/components/StockAutocomplete/StockAutocomplete.vue';
import HoldingsPage from '../market/HoldingsPage.vue';

vi.mock('@/composables/useRealtimeQuotes', async () => {
  const { ref } = await import('vue');
  return { useRealtimeQuotes: () => ({ portfolio: ref(null), status: ref('connected'), getQuote: () => undefined }) };
});

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

async function settleDetail() {
  await vi.dynamicImportSettled();
  await flushPromises();
  const holdingsTab = wrapper.findAll('[role="tab"]').find(tab => tab.text() === '持仓');
  if (holdingsTab) await holdingsTab.trigger('mousedown', { button: 0, ctrlKey: false });
  await vi.dynamicImportSettled();
  await flushPromises();
}

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
        ResearchEvidence: true,
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
    vi.resetAllMocks();
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
    expect(mocks.setCash).toHaveBeenCalledWith({ accountId: 1, amount: '100000', operationId: expect.any(String) });
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
      accountId: 1, symbol: '510300.SH', assetType: 'ETF', quantity: '100', price: '4', operationId: expect.any(String),
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
    await settleDetail();
    await flushPromises();
    expect(wrapper.text()).toContain('交易提醒');
    await wrapper.get('[data-testid="trade-engine-enabled"]').setValue(false);
    await flushPromises();
    expect(mocks.updatePosition).toHaveBeenCalledWith(11, { tradeEngineEnabled: false });
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe('holdings request ownership', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.summary.mockResolvedValue(summary);
    mocks.positions.mockResolvedValue([]);
    mocks.operations.mockResolvedValue([]);
    mocks.markers.mockResolvedValue([]);
  });
  afterEach(() => wrapper?.unmount());

  it('loads holdings without waiting for engine and exposes engine failures with independent retry', async () => {
    const engine = deferred<unknown[]>();
    mocks.positions.mockReturnValueOnce(engine.promise);
    await mountPage();
    expect(wrapper.get('[data-testid="cash"]').text()).toContain('90,000');
    expect(wrapper.text()).toContain('加载中');
    engine.reject(new Error('offline'));
    await flushPromises();
    expect(wrapper.get('[data-testid="engine-error"]').text()).toContain('Trade Engine 建议读取失败');
    await wrapper.get('[data-testid="retry-engine"]').trigger('click');
    await flushPromises();
    expect(mocks.summary).toHaveBeenCalledTimes(1);
    expect(mocks.positions).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="engine-error"]').exists()).toBe(false);
  });

  it('ignores old market successes, errors and finally callbacks', async () => {
    const cn = deferred<typeof summary>();
    const cnEngine = deferred<unknown[]>();
    const us = { ...summary, market: 'US', cash: '222', accounts: [{ ...summary.accounts[0]!, id: 2, market: 'US' }],
      positions: [{ ...summary.positions[0]!, id: 12, market: 'US', symbol: 'AAPL.US' }] };
    mocks.summary.mockReturnValueOnce(cn.promise).mockResolvedValueOnce(us);
    mocks.positions.mockReturnValueOnce(cnEngine.promise).mockResolvedValueOnce([]);
    await mountPage();
    expect(wrapper.get('[data-testid="action-buy"]').attributes('disabled')).toBeDefined();
    await wrapper.get('[data-testid="market-us"]').trigger('click');
    await flushPromises();
    cn.resolve(summary); cnEngine.reject(new Error('old market'));
    await flushPromises();
    expect(wrapper.text()).toContain('AAPL.US');
    expect(wrapper.text()).not.toContain('600519.SH');
    expect(wrapper.get('[data-testid="cash"]').text()).toBe('222');
    expect(wrapper.find('[data-testid="engine-error"]').exists()).toBe(false);
  });

  it('clears forms and details on market change and ignores delayed detail or mutation completions', async () => {
    const ops = deferred<unknown[]>();
    const save = deferred<unknown>();
    mocks.operations.mockReturnValueOnce(ops.promise);
    mocks.setCash.mockReturnValueOnce(save.promise);
    await mountPage();
    await wrapper.get('button.text-left').trigger('click');
    await settleDetail();
    await wrapper.get('[data-testid="action-cash"]').trigger('click');
    await wrapper.get('[data-testid="form-submit"]').trigger('click');
    const us = { ...summary, market: 'US', positions: [], accounts: [{ ...summary.accounts[0]!, id: 2, market: 'US' }] };
    mocks.summary.mockResolvedValue(us);
    await wrapper.get('[data-testid="market-us"]').trigger('click');
    await flushPromises();
    await wrapper.get('[data-testid="action-cash"]').trigger('click');
    ops.resolve([{ executedAt: 'old', side: 'BUY', quantity: '99', price: '1' }]); save.resolve({});
    await flushPromises();
    expect(wrapper.find('[data-testid="trade-engine-enabled"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="form-submit"]').exists()).toBe(true);
    expect(mocks.summary).toHaveBeenCalledTimes(3); // List, lazy holding panel, then new market.
    expect(wrapper.text()).not.toContain('old');
  });

  it('uses the same operation id when a timed-out submission is retried', async () => {
    mocks.setCash.mockRejectedValueOnce(new Error('timeout')).mockResolvedValueOnce({});
    await mountPage();
    await wrapper.get('[data-testid="action-cash"]').trigger('click');
    await wrapper.get('[data-testid="form-submit"]').trigger('click');
    await flushPromises();
    await wrapper.get('[data-testid="form-submit"]').trigger('click');
    await flushPromises();
    expect(mocks.setCash).toHaveBeenCalledTimes(2);
    expect(mocks.setCash.mock.calls[0]![0].operationId).toMatch(/^[a-f0-9-]{36}$/);
    expect(mocks.setCash.mock.calls[1]![0]).toEqual(mocks.setCash.mock.calls[0]![0]);
  });

  it('ignores previous position operations and exposes current detail errors', async () => {
    const old = deferred<unknown[]>();
    mocks.summary.mockResolvedValue({ ...summary, positions: [...summary.positions, { ...summary.positions[0]!, id: 22, symbol: '510300.SH' }] });
    mocks.operations.mockReturnValueOnce(old.promise).mockRejectedValueOnce(new Error('details unavailable'));
    await mountPage();
    await wrapper.findAll('button.text-left')[0]!.trigger('click');
    await settleDetail();
    await wrapper.findAll('button.text-left')[1]!.trigger('click');
    await settleDetail();
    old.resolve([{ executedAt: 'old-operation', side: 'BUY', quantity: '999', price: '1' }]);
    await flushPromises();
    expect(wrapper.text()).toContain('重试详情');
    expect(wrapper.text()).not.toContain('old-operation');
  });

  it('does not apply a delayed toggle to another position', async () => {
    const toggle = deferred<unknown>();
    mocks.summary.mockResolvedValue({ ...summary, positions: [...summary.positions, { ...summary.positions[0]!, id: 22, symbol: '510300.SH' }] });
    mocks.updatePosition.mockReturnValueOnce(toggle.promise);
    await mountPage();
    await wrapper.findAll('button.text-left')[0]!.trigger('click');
    await settleDetail();
    await wrapper.get('[data-testid="trade-engine-enabled"]').setValue(false);
    await wrapper.findAll('button.text-left')[1]!.trigger('click');
    await settleDetail();
    toggle.resolve({ ...summary.positions[0], tradeEngineEnabled: false });
    await flushPromises();
    expect((wrapper.get('[data-testid="trade-engine-enabled"]').element as HTMLInputElement).checked).toBe(true);
  });
});

it('creates mutation ids on non-secure LAN origins without randomUUID', () => {
  const getRandomValues = crypto.getRandomValues.bind(crypto);
  vi.stubGlobal('crypto', { getRandomValues });
  try {
    const first = createOperationId();
    expect(first).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
    expect(createOperationId()).not.toBe(first);
  } finally { vi.unstubAllGlobals(); }
});

it('shows names, daily change and PnL, removes market value, and sorts missing values last', async () => {
  const priced = { ...summary.positions[0]!, name: '贵州茅台', changePct: '2.5', changeAmount: '0.3', dayPnl: '300', unrealizedPnlPct: '20', quoteSource: 'fuyao', quoteTime: '2026-07-16T02:40:00Z', quoteStatus: 'current' };
  mocks.summary.mockResolvedValue({ ...summary, missingQuoteCount: 1, positions: [priced,
    { ...priced, id: 22, symbol: '510300.SH', name: '沪深300ETF', changePct: '-1' },
    { ...priced, id: 33, symbol: '000001.SZ', name: '平安银行', currentPrice: null, changePct: null },
  ] });
  await mountPage();
  const headers = wrapper.findAll('thead th').map(header => header.text());
  expect(headers.join()).not.toContain('市值');
  expect(headers.join()).toContain('当日涨跌');
  const first = wrapper.findAll('[data-testid="position-row"]')[0]!;
  expect(first.text()).toContain('贵州茅台');
  expect(first.text()).toContain('+20.00%');
  expect(first.text()).toContain('+2,000.00');
  expect(wrapper.get('[data-testid="valuation-incomplete"]').text()).toContain('1 只');
  const column = wrapper.findAll('thead th').find(header => header.text().includes('当日涨跌'))!;
  await column.get('button').trigger('click');
  expect(wrapper.findAll('[data-testid="position-row"]').map(row => row.text().includes('平安银行'))).toEqual([false, false, true]);
  expect(wrapper.findAll('[data-testid="position-row"]')[0]!.text()).toContain('贵州茅台');
  await column.get('button').trigger('click');
  expect(wrapper.findAll('[data-testid="position-row"]')[0]!.text()).toContain('沪深300ETF');
  expect(wrapper.findAll('[data-testid="position-row"]')[2]!.text()).toContain('平安银行');
  wrapper.unmount();
});
