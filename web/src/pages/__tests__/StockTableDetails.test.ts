import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { nextTick } from 'vue';
import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StockListPage from '../StockListPage.vue';
import WatchListPage from '../WatchListPage.vue';

const mocks = vi.hoisted(() => ({
  getQuote: vi.fn(),
  listHoldings: vi.fn(),
  listWatchItems: vi.fn(),
  updateHolding: vi.fn(),
  updateWatchItem: vi.fn(),
}));

vi.mock('@/api/stockList', () => ({
  stockListApi: {
    create: vi.fn(),
    list: mocks.listHoldings,
    remove: vi.fn(),
    update: mocks.updateHolding,
  },
}));

vi.mock('@/api/watchList', () => ({
  watchListApi: {
    create: vi.fn(),
    list: mocks.listWatchItems,
    remove: vi.fn(),
    update: mocks.updateWatchItem,
  },
}));

vi.mock('@/composables/useRealtimeQuotes', async () => {
  const { ref } = await import('vue');
  return {
    useRealtimeQuotes: () => ({
      getQuote: mocks.getQuote,
      status: ref('connected'),
    }),
  };
});

const watchItem = {
  id: 11,
  code: 'AAPL',
  name: 'Apple',
  market_type: 'US' as const,
  notes: '等待财报确认',
  is_favorite: true,
  created_at: '2026-06-01T01:00:00Z',
  updated_at: '2026-06-02T02:00:00Z',
};

const holding = {
  id: 22,
  code: 'AAPL',
  name: 'Apple',
  market_type: 'US' as const,
  quantity: '10',
  avg_cost: '8',
  opened_at: '2026-05-01T00:00:00Z',
  notes: '核心仓位',
  created_at: '2026-05-01T00:00:00Z',
  updated_at: '2026-06-02T02:00:00Z',
};

const quote = {
  code: 'AAPL',
  market_type: 'US' as const,
  symbol: 'AAPL.US',
  available: true,
  last_price: 12,
  change_amount: 0.5,
  change_pct: 4.35,
  open: 11.5,
  high: 12.2,
  low: 11.4,
  pre_close: 11.5,
  volume: 123456,
  turnover: 1456789,
  trade_session: 'Regular',
  event_time: '2026-07-03T15:00:00Z',
  received_at: '2026-07-03T15:00:01Z',
};

let wrapper: VueWrapper | null = null;

async function mountPage(component: typeof WatchListPage | typeof StockListPage, path: string) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/market/watch-list', name: 'market-watch-list', component: WatchListPage },
      { path: '/market/holdings', name: 'market-holdings', component: StockListPage },
    ],
  });
  await router.push(path);
  await router.isReady();
  wrapper = mount(component, {
    attachTo: document.body,
    global: {
      plugins: [pinia, router],
      stubs: {
        RealtimeStatus: true,
        StockAutocomplete: true,
      },
    },
  });
  await flushPromises();
  return wrapper;
}

describe('stock table details', () => {
  beforeEach(() => {
    mocks.getQuote.mockReturnValue(quote);
    mocks.listWatchItems.mockResolvedValue({ items: [watchItem], total: 1 });
    mocks.listHoldings.mockResolvedValue({ items: [holding], total: 1 });
  });

  afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('opens complete watch-list details by clicking the row or pressing Enter', async () => {
    const page = await mountPage(WatchListPage, '/market/watch-list');
    const row = page.get('tbody tr[tabindex="0"]');

    await row.trigger('click');
    let dialog = document.body.querySelector<HTMLElement>('[role="dialog"]');
    expect(dialog?.textContent).toContain('Apple');
    expect(dialog?.textContent).toContain('AAPL.US');
    expect(dialog?.textContent).toContain('特别关注');
    expect(dialog?.textContent).toContain('等待财报确认');
    expect(dialog?.textContent).toContain('记录 ID');
    expect(dialog?.textContent).toContain('11');

    document.body.querySelector<HTMLButtonElement>('button[aria-label="关闭详情"]')?.click();
    await nextTick();
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();

    await row.trigger('keydown', { key: 'Enter' });
    dialog = document.body.querySelector<HTMLElement>('[role="dialog"]');
    expect(dialog?.textContent).toContain('自选信息');
  });

  it('opens holding details with calculated market value and profit fields', async () => {
    const page = await mountPage(StockListPage, '/market/holdings');

    await page.get('tbody tr[tabindex="0"]').trigger('click');
    const dialog = document.body.querySelector<HTMLElement>('[role="dialog"]');
    expect(dialog?.textContent).toContain('最新市值');
    expect(dialog?.textContent).toContain('$120.00');
    expect(dialog?.textContent).toContain('浮动盈亏');
    expect(dialog?.textContent).toContain('+$40.00');
    expect(dialog?.textContent).toContain('持仓收益率');
    expect(dialog?.textContent).toContain('+50.00%');
    expect(dialog?.textContent).toContain('核心仓位');
  });

  it('does not open details when an action button is clicked', async () => {
    const page = await mountPage(StockListPage, '/market/holdings');

    await page.get('button[aria-label="编辑"]').trigger('click');

    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    expect(document.body.textContent).toContain('编辑持仓股');
  });
});
