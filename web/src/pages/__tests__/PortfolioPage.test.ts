import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StockListPage from '../StockListPage.vue';

const mocks = vi.hoisted(() => ({
  createEquity: vi.fn(),
  createOption: vi.fn(),
  listAccounts: vi.fn(),
  listPositions: vi.fn(),
  removePosition: vi.fn(),
  updateCash: vi.fn(),
  updatePosition: vi.fn(),
}));

vi.mock('@/api/portfolio', () => ({
  portfolioApi: mocks,
}));

vi.mock('@/composables/useRealtimeQuotes', () => ({
  useRealtimeQuotes: () => ({
    getQuote: (code: string) => (code === 'AAPL' ? { last_price: 120 } : undefined),
  }),
}));

const accounts = [
  { id: 1, account_code: 'CN', name: 'A股账户', market: 'CN', currency: 'CNY', cash_balance: '1000.00' },
  { id: 2, account_code: 'HK', name: '港股账户', market: 'HK', currency: 'HKD', cash_balance: '2000.00' },
  { id: 3, account_code: 'US', name: '美股账户', market: 'US', currency: 'USD', cash_balance: '3000.00' },
] as const;

const cnEtf = {
  id: 10,
  account_id: 1,
  account_code: 'CN',
  asset_type: 'ETF',
  market: 'CN',
  currency: 'CNY',
  canonical_symbol: '510300.SH',
  display_symbol: '510300',
  name: '沪深300ETF',
  quantity: '10',
  position_side: 'LONG',
  avg_cost: '4',
  contract_multiplier: '1',
  cost_amount: '40',
  opened_at: null,
  status: 'OPEN',
  closed_at: null,
  notes: null,
  created_at: '2026-07-01T00:00:00Z',
  updated_at: '2026-07-01T00:00:00Z',
  option: null,
};

const usStock = {
  ...cnEtf,
  id: 20,
  account_id: 3,
  account_code: 'US',
  asset_type: 'STOCK',
  market: 'US',
  currency: 'USD',
  canonical_symbol: 'AAPL.US',
  display_symbol: 'AAPL',
  name: 'Apple',
  avg_cost: '100',
  cost_amount: '1000',
};

const expiredOption = {
  ...usStock,
  id: 21,
  asset_type: 'OPTION',
  canonical_symbol: 'SPY.US|2026-07-20|PUT|600',
  display_symbol: 'SPY 2026-07-20 600P',
  name: 'SPY Put',
  quantity: '-2',
  position_side: 'SHORT',
  avg_cost: '3.5',
  contract_multiplier: '100',
  cost_amount: '700',
  option: {
    underlying_canonical_symbol: 'SPY.US',
    underlying_display_symbol: 'SPY',
    underlying_name: 'SPDR S&P 500 ETF Trust',
    option_type: 'PUT',
    expiration_date: '2026-07-20',
    strike_price: '600',
    days_to_expiration: -9,
    expiration_action_required: true,
  },
};

const StockAutocompleteStub = {
  name: 'StockAutocomplete',
  props: ['modelValue'],
  emits: ['update:modelValue', 'submit'],
  template: '<button type="button" data-testid="select-security">选择测试标的</button>',
};

let wrapper: VueWrapper | null = null;

async function mountPage(): Promise<VueWrapper> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/market/holdings', component: StockListPage }],
  });
  await router.push('/market/holdings');
  await router.isReady();
  wrapper = mount(StockListPage, {
    attachTo: document.body,
    global: {
      plugins: [createPinia(), router],
      stubs: { StockAutocomplete: StockAutocompleteStub },
    },
  });
  await flushPromises();
  return wrapper;
}

function setField(labelText: string, value: string): void {
  const labels = Array.from(document.body.querySelectorAll('label'));
  const label = labels.find((item) => item.textContent?.includes(labelText));
  const nested = label?.querySelector<HTMLInputElement | HTMLSelectElement>('input, select, textarea');
  const input = nested ?? (label?.htmlFor ? document.getElementById(label.htmlFor) : null);
  if (!input) throw new Error(`Missing field ${labelText}`);
  (input as HTMLInputElement | HTMLSelectElement).value = value;
  input.dispatchEvent(new Event(input instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
}

describe('portfolio page', () => {
  beforeEach(() => {
    mocks.listAccounts.mockResolvedValue([...accounts]);
    mocks.listPositions.mockImplementation((accountId: number) =>
      Promise.resolve(accountId === 3 ? [usStock, expiredOption] : accountId === 1 ? [cnEtf] : []),
    );
    mocks.createEquity.mockResolvedValue(cnEtf);
    mocks.createOption.mockResolvedValue(expiredOption);
    mocks.updateCash.mockResolvedValue(accounts[0]);
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('renders exactly three fixed account tabs and defaults to CN without account management', async () => {
    const page = await mountPage();
    expect(page.findAll('[role="tab"]')).toHaveLength(3);
    expect(page.get('[data-account-code="CN"]').attributes('aria-selected')).toBe('true');
    expect(page.text()).toContain('存在未定价股票/ETF');
    expect(page.find('[data-testid="add-option"]').exists()).toBe(false);
    expect(page.text()).not.toContain('新建账户');
    expect(page.text()).not.toContain('编辑账户');
    expect(mocks.listPositions).toHaveBeenCalledWith(1, 'ALL', 'ALL');
  });

  it('shows US options as non-priced records with DTE actions and mobile cards', async () => {
    const page = await mountPage();
    await page.get('[data-account-code="US"]').trigger('click');
    await flushPromises();
    expect(page.find('[data-testid="add-option"]').exists()).toBe(true);
    const section = page.get('[data-testid="option-section"]');
    expect(section.text()).toContain('期权仅作手工持仓记录，不提供实时价格、市值或盈亏');
    expect(section.text()).toContain('已到期，待确认处理');
    expect(section.text()).toContain('标记已平仓');
    expect(section.text()).toContain('标记失效');
    expect(section.findAll('article')).toHaveLength(1);
    const optionHeaders = section.findAll('thead th').map((item) => item.text());
    expect(optionHeaders).not.toContain('最新价格');
    expect(optionHeaders).not.toContain('持仓市值');
    expect(optionHeaders).not.toContain('未实现盈亏');
  });

  it('maps autocomplete ETF asset type separately from its CN market and submits strings', async () => {
    const page = await mountPage();
    const add = page.findAll('button').find((item) => item.text().includes('添加股票 / ETF'))!;
    await add.trigger('click');
    const autocomplete = page.findComponent({ name: 'StockAutocomplete' });
    autocomplete.vm.$emit('submit', '510300.SH', '沪深300ETF', 'autocomplete', 'CN', 'etf');
    await flushPromises();
    setField('数量', '10.25');
    setField('平均成本', '4.12345678');
    document.body.querySelector('form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await flushPromises();
    expect(mocks.createEquity).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        canonical_symbol: '510300.SH',
        display_symbol: '510300',
        asset_type: 'ETF',
        quantity: '10.25',
        avg_cost: '4.12345678',
      }),
    );
  });

  it('submits short option quantity and default multiplier 100 as decimal strings', async () => {
    const page = await mountPage();
    await page.get('[data-account-code="US"]').trigger('click');
    await flushPromises();
    await page.get('[data-testid="add-option"]').trigger('click');
    page.findComponent({ name: 'StockAutocomplete' }).vm.$emit(
      'submit',
      'SPY.US',
      'SPDR S&P 500 ETF Trust',
      'autocomplete',
      'US',
      'etf',
    );
    await flushPromises();
    setField('到期日', '2026-08-21');
    setField('行权价', '650');
    setField('张数', '2');
    setField('持仓方向', 'SHORT');
    setField('平均成本', '3.50');
    document.body.querySelector('form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await flushPromises();
    expect(mocks.createOption).toHaveBeenCalledWith(
      3,
      expect.objectContaining({
        underlying_asset_type: 'ETF',
        quantity: '-2',
        avg_cost: '3.50',
        contract_multiplier: '100',
      }),
    );
  });
});
