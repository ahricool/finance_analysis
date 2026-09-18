import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StockListPage from '../StockListPage.vue';

const mocks = vi.hoisted(() => ({
  source: vi.fn(),
  connect: vi.fn(),
  disconnect: vi.fn(),
  sync: vi.fn(),
  snapshot: vi.fn(),
  policy: vi.fn(),
  updatePolicy: vi.fn(),
  risk: vi.fn(),
  runRisk: vi.fn(),
  cancelPlan: vi.fn(),
  rebase: vi.fn(),
}));

vi.mock('@/api/holdings', () => ({
  holdingsApi: mocks,
}));

const source = {
  googleConfigured: true,
  holdingsEnabled: true,
  missingConfig: [],
  sourceId: 1,
  spreadsheetId: 'sheet-1',
  schemaVersion: 'v1',
  authStatus: 'CONNECTED',
  syncStatus: 'OK',
  enabled: true,
  lastAttemptAt: null,
  lastSuccessAt: null,
  lastErrorCode: null,
  publishedGeneration: 2,
  contentHash: 'abc',
  configVersion: 1,
  policyVersion: 1,
  canBackgroundSync: true,
};

const snapshot = {
  status: 'VALID',
  snapshot: {
    status: 'VALID',
    generation: 2,
    accounts: [{ accountId: 'a1', accountName: 'A股', baseCurrency: 'CNY', netAsset: '100000', validity: 'VALID', positionsComplete: true }],
    positions: [
      {
        accountId: 'a1',
        positionId: 'p1',
        symbol: '600519.SH',
        canonicalSymbol: '600519.SH',
        assetType: 'STOCK',
        legs: [
          {
            accountId: 'a1',
            positionId: 'p1',
            legId: 'core',
            legRole: 'CORE',
            symbol: '600519.SH',
            canonicalSymbol: '600519.SH',
            assetType: 'STOCK',
            quantity: '1000',
            entryPrice: '1400',
            entryTime: '2026-01-01T01:00:00+00:00',
            status: 'OPEN',
            coverage: 'COVERED',
            coverageReason: null,
            initialStop: null,
          },
        ],
      },
    ],
    uncoveredLegs: [],
    warnings: [],
  },
};

let wrapper: VueWrapper | null = null;

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/market/holdings', component: StockListPage }],
  });
  await router.push('/market/holdings');
  await router.isReady();
  wrapper = mount(StockListPage, {
    global: { plugins: [createPinia(), router] },
  });
  await flushPromises();
}

describe('holdings page', () => {
  beforeEach(() => {
    mocks.source.mockResolvedValue(source);
    mocks.snapshot.mockResolvedValue(snapshot);
    mocks.policy.mockResolvedValue({ policy: { vwapMode: 'exact_or_proxy' }, policyVersion: 1 });
    mocks.risk.mockResolvedValue({
      source: { id: 1, generation: 2 },
      snapshot: snapshot.snapshot,
      positions: [
        {
          accountId: 'a1',
          positionId: 'p1',
          symbol: '600519.SH',
          planStatus: 'PENDING',
          planAction: 'REDUCE',
          planRevision: 1,
          rowVersion: 3,
          lastBarEnd: '2026-09-16T06:00:00+00:00',
          lastQuoteAsOf: '2026-09-16T06:00:01+00:00',
          fiveMinuteStatus: 'OK',
          quoteStatus: 'OK',
          execution: 'UNKNOWN',
          currentQuantity: '1000',
          reduceQuantity: '500',
          activePlan: { position_target: '500', reduce_quantity: '500', current_quantity: '1000', execution: 'UNKNOWN' },
          legsState: { five_minute_status: 'OK', quote_status: 'OK', legs: { core: { active_stop: '96', profit_stage: 'B' } } },
        },
      ],
      events: [
        {
          id: 9,
          eventType: 'CONFIRMED_WEAK',
          action: 'REDUCE',
          positionId: 'p1',
          legId: null,
          targetQuantity: '500',
          createdAt: '2026-09-17T07:00:00+00:00',
          notificationId: 44,
          pushStatus: 'SENT',
          evidence: { vwap_mode: 'PROXY' },
        },
      ],
    });
    mocks.connect.mockResolvedValue({ authorization_url: 'https://accounts.google.com/o', return_path: '/market/holdings', auth_status: 'PENDING' });
    mocks.sync.mockResolvedValue({ task_id: 't1', status: 'queued' });
    mocks.cancelPlan.mockResolvedValue({ plan_status: 'CANCELED', row_version: 4 });
    mocks.disconnect.mockResolvedValue({ auth_status: 'DISCONNECTED' });
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    vi.clearAllMocks();
  });

  it('renders sheet-backed holdings and risk evidence without portfolio CRUD', async () => {
    await mountPage();
    expect(wrapper!.text()).toContain('Google Sheet 持仓');
    expect(wrapper!.text()).toContain('全局 Telegram/ntfy');
    expect(wrapper!.text()).toContain('600519.SH');
    expect(wrapper!.text()).toContain('CORE');
    expect(wrapper!.text()).toContain('PROXY');
    expect(wrapper!.text()).toContain('1000');
    expect(wrapper!.text()).toContain('500');
    expect(wrapper!.text()).toContain('96');
    expect(wrapper!.text()).toContain('OK / OK');
    expect(wrapper!.find('[data-testid="portfolio-page"]').exists()).toBe(false);
    expect(wrapper!.find('[data-testid="holdings-page"]').exists()).toBe(true);
  });

  it('starts Google connect from a spreadsheet id', async () => {
    const assign = vi.fn();
    vi.stubGlobal('location', { ...window.location, assign });
    await mountPage();
    await wrapper!.get('[data-testid="spreadsheet-input"]').setValue('1abcSpreadsheetIdValueXX');
    await wrapper!.get('[data-testid="connect-button"]').trigger('click');
    await flushPromises();
    expect(mocks.connect).toHaveBeenCalledWith('1abcSpreadsheetIdValueXX');
    expect(assign).toHaveBeenCalledWith('https://accounts.google.com/o');
    vi.unstubAllGlobals();
  });

  it('saves VWAP without dropping other policy fields and waits after queued sync', async () => {
    mocks.policy.mockResolvedValue({
      policy: { vwapMode: 'exact_or_proxy', maxSymbolWeight: 0.1, riskPerSymbol: 0.005 },
      policyVersion: 1,
    });
    mocks.sync.mockResolvedValue({ task_id: 't1', status: 'queued' });
    await mountPage();
    await wrapper!.get('[data-testid="vwap-mode"]').setValue('exact_only');
    await wrapper!.get('[data-testid="save-policy"]').trigger('click');
    await flushPromises();
    expect(mocks.updatePolicy).toHaveBeenCalled();
    const payload = mocks.updatePolicy.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.vwap_mode || payload.vwapMode).toBe('exact_only');
    expect(payload.maxSymbolWeight ?? payload.max_symbol_weight).toBe(0.1);
    await wrapper!.get('[data-testid="sync-button"]').trigger('click');
    await flushPromises();
    expect(mocks.sync).toHaveBeenCalled();
  });

  it('cancels a pending plan', async () => {
    await mountPage();
    await wrapper!.get('[data-testid="cancel-p1"]').trigger('click');
    await flushPromises();
    expect(mocks.cancelPlan).toHaveBeenCalledWith({
      accountId: 'a1',
      positionId: 'p1',
      expectedStateVersion: 3,
      reason: 'manual_cancel',
    });
  });
});
