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

async function selectCreateAssetType(assetType: 'STOCK' | 'ETF' | 'OPTION'): Promise<void> {
  const input = document.body.querySelector<HTMLInputElement>(`[data-create-asset-type="${assetType}"]`);
  if (!input) throw new Error(`Missing create asset type ${assetType}`);
  input.checked = true;
  input.dispatchEvent(new Event('change', { bubbles: true }));
  await flushPromises();
}

async function clickDialogButton(text: string): Promise<void> {
  const button = Array.from(document.body.querySelectorAll('button')).find(
    (item) => item.textContent?.trim() === text,
  );
  if (!button) throw new Error(`Missing dialog button ${text}`);
  button.click();
  await flushPromises();
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
    expect(page.findAll('[data-testid="add-position"]')).toHaveLength(1);
    expect(page.text()).not.toContain('新建账户');
    expect(page.text()).not.toContain('编辑账户');
    expect(mocks.listPositions).toHaveBeenCalledWith(1, 'ALL', 'ALL');
  });

  it('shows US options as non-priced records with DTE actions and mobile cards', async () => {
    const page = await mountPage();
    await page.get('[data-account-code="US"]').trigger('click');
    await flushPromises();
    expect(page.find('[data-testid="add-position"]').exists()).toBe(true);
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

  it('uses the ETF radio as the final asset type even when autocomplete reports stock', async () => {
    const page = await mountPage();
    await page.get('[data-testid="add-position"]').trigger('click');
    await selectCreateAssetType('ETF');
    const autocomplete = page.findComponent({ name: 'StockAutocomplete' });
    autocomplete.vm.$emit('update:modelValue', '510300');
    autocomplete.vm.$emit('submit', '510300.SH', '沪深300ETF', 'autocomplete', 'CN', 'stock');
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
    await page.get('[data-testid="add-position"]').trigger('click');
    await selectCreateAssetType('OPTION');
    const underlyingTypeRadios = document.body.querySelectorAll<HTMLInputElement>(
      'input[name="option-underlying-type"]',
    );
    underlyingTypeRadios[1]!.checked = true;
    underlyingTypeRadios[1]!.dispatchEvent(new Event('change', { bubbles: true }));
    const autocomplete = page.findComponent({ name: 'StockAutocomplete' });
    autocomplete.vm.$emit('update:modelValue', 'SPY');
    autocomplete.vm.$emit(
      'submit',
      'SPY',
      'SPDR S&P 500 ETF Trust',
      'autocomplete',
      'US',
      'etf',
    );
    await flushPromises();
    expect(document.body.textContent).toContain('合约乘数：100');
    const optionDialog = document.body.querySelector('[role="dialog"]');
    expect(optionDialog?.textContent).toContain('张数');
    expect(
      Array.from(optionDialog?.querySelectorAll('label') ?? []).some(
        (label) => label.textContent?.trim() === '数量',
      ),
    ).toBe(false);
    expect(
      Array.from(document.body.querySelectorAll('label')).some((label) => label.textContent?.includes('合约乘数')),
    ).toBe(false);
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
        underlying_canonical_symbol: 'SPY',
        quantity: '-2',
        avg_cost: '3.50',
        contract_multiplier: '100',
      }),
    );
  });

  it('shows create radios by account and never exposes option creation for CN or HK', async () => {
    const page = await mountPage();
    await page.get('[data-testid="add-position"]').trigger('click');
    expect(document.body.querySelectorAll('input[name="create-asset-type"]')).toHaveLength(2);
    expect(document.body.querySelector('[data-create-asset-type="OPTION"]')).toBeNull();

    await clickDialogButton('取消');
    await page.get('[data-account-code="HK"]').trigger('click');
    await flushPromises();
    await page.get('[data-testid="add-position"]').trigger('click');
    expect(document.body.querySelectorAll('input[name="create-asset-type"]')).toHaveLength(2);
    expect(document.body.querySelector('[data-create-asset-type="OPTION"]')).toBeNull();

    await clickDialogButton('取消');
    await page.get('[data-account-code="US"]').trigger('click');
    await flushPromises();
    await page.get('[data-testid="add-position"]').trigger('click');
    expect(document.body.querySelectorAll('input[name="create-asset-type"]')).toHaveLength(3);
  });

  it('submits STOCK from the radio and replaces a selection after edited autocomplete text', async () => {
    const page = await mountPage();
    await page.get('[data-account-code="US"]').trigger('click');
    await flushPromises();
    await page.get('[data-testid="add-position"]').trigger('click');
    const autocomplete = page.findComponent({ name: 'StockAutocomplete' });
    autocomplete.vm.$emit('update:modelValue', 'AAPL');
    autocomplete.vm.$emit('submit', 'AAPL', 'Apple', 'autocomplete', 'US', 'etf');
    await flushPromises();
    setField('数量', '2');
    setField('平均成本', '100');

    autocomplete.vm.$emit('update:modelValue', 'MSFT');
    document.body.querySelector('form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await flushPromises();
    expect(document.body.textContent).toContain('请从搜索结果中选择标的');
    expect(mocks.createEquity).not.toHaveBeenCalled();

    autocomplete.vm.$emit('update:modelValue', 'MSFT');
    autocomplete.vm.$emit('submit', 'MSFT', 'Microsoft', 'autocomplete', 'US', 'stock');
    await flushPromises();
    document.body.querySelector('form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await flushPromises();
    expect(mocks.createEquity).toHaveBeenCalledWith(
      3,
      expect.objectContaining({ canonical_symbol: 'MSFT', asset_type: 'STOCK' }),
    );
  });

  it('invalidates edited ETF and option underlyings until a new result is selected', async () => {
    const page = await mountPage();
    await page.get('[data-testid="add-position"]').trigger('click');
    await selectCreateAssetType('ETF');
    let autocomplete = page.findComponent({ name: 'StockAutocomplete' });
    autocomplete.vm.$emit('update:modelValue', '510300');
    autocomplete.vm.$emit('submit', '510300.SH', '沪深300ETF', 'autocomplete', 'CN', 'stock');
    setField('数量', '10');
    setField('平均成本', '4');
    autocomplete.vm.$emit('update:modelValue', '510500');
    document.body.querySelector('form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await flushPromises();
    expect(mocks.createEquity).not.toHaveBeenCalled();

    await clickDialogButton('取消');
    await page.get('[data-account-code="US"]').trigger('click');
    await flushPromises();
    await page.get('[data-testid="add-position"]').trigger('click');
    await selectCreateAssetType('OPTION');
    autocomplete = page.findComponent({ name: 'StockAutocomplete' });
    autocomplete.vm.$emit('update:modelValue', 'SPY');
    autocomplete.vm.$emit('submit', 'SPY', 'SPY ETF', 'autocomplete', 'US', 'stock');
    setField('到期日', '2026-08-21');
    setField('行权价', '650');
    setField('张数', '1');
    setField('平均成本', '3');
    autocomplete.vm.$emit('update:modelValue', 'QQQ');
    document.body.querySelector('form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await flushPromises();
    expect(mocks.createOption).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('请从搜索结果中选择标的');
  });

  it('clears symbol and type-specific fields whenever the create asset radio changes', async () => {
    const page = await mountPage();
    await page.get('[data-account-code="US"]').trigger('click');
    await flushPromises();
    await page.get('[data-testid="add-position"]').trigger('click');
    let autocomplete = page.findComponent({ name: 'StockAutocomplete' });
    autocomplete.vm.$emit('update:modelValue', 'AAPL');
    autocomplete.vm.$emit('submit', 'AAPL', 'Apple', 'autocomplete', 'US', 'stock');
    setField('数量', '2');
    setField('平均成本', '100');

    await selectCreateAssetType('OPTION');
    autocomplete = page.findComponent({ name: 'StockAutocomplete' });
    expect(autocomplete.props('modelValue')).toBe('');
    setField('到期日', '2026-08-21');
    setField('行权价', '650');
    autocomplete.vm.$emit('update:modelValue', 'SPY');
    autocomplete.vm.$emit('submit', 'SPY', 'SPY ETF', 'autocomplete', 'US', 'etf');

    await selectCreateAssetType('ETF');
    autocomplete = page.findComponent({ name: 'StockAutocomplete' });
    expect(autocomplete.props('modelValue')).toBe('');
    expect((document.querySelector('input[inputmode="decimal"]') as HTMLInputElement).value).toBe('');
    const dialogText = document.body.querySelector('[role="dialog"]')?.textContent;
    expect(dialogText).not.toContain('行权价');
    expect(dialogText).not.toContain('到期日');
  });
});
