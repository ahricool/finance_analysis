import { flushPromises, mount } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import WatchListPage from '../WatchListPage.vue';

const mocks = vi.hoisted(() => ({
  getQuote: vi.fn(),
  listWatchItems: vi.fn(),
  updateWatchItem: vi.fn(),
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
  return { useRealtimeQuotes: () => ({ getQuote: mocks.getQuote, status: ref('connected') }) };
});

vi.mock('@/composables/useCurrentTime', async () => {
  const { ref } = await import('vue');
  return { useCurrentTime: () => ref(new Date('2026-07-03T15:00:00Z')) };
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

const quote = {
  code: 'AAPL',
  market_type: 'US' as const,
  symbol: 'AAPL.US',
  available: true,
  last_price: 12,
  change_amount: 0.5,
  change_pct: 4.35,
  trend_1m: { timeframe: '1m' as const, target_period: 20, effective_period: 8, minimum_period: 5, state: 'above' as const, streak: 2, confirmed: true },
  pattern_1m: { timeframe: '1m' as const, status: 'none' as const, signal: null },
};

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/market/watch-list', name: 'market-watch-list', component: WatchListPage }],
  });
  await router.push('/market/watch-list');
  await router.isReady();
  const wrapper = mount(WatchListPage, {
    attachTo: document.body,
    global: { plugins: [createPinia(), router], stubs: { StockAutocomplete: true } },
  });
  await flushPromises();
  return wrapper;
}

describe('watch-list table details', () => {
  beforeEach(() => {
    mocks.getQuote.mockReturnValue(quote);
    mocks.listWatchItems.mockResolvedValue({ items: [watchItem], total: 1 });
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('opens complete details from the row', async () => {
    const page = await mountPage();
    await page.get('tbody tr[tabindex="0"]').trigger('click');
    expect(document.body.textContent).toContain('Apple');
    expect(document.body.textContent).toContain('等待财报确认');
  });

  it('keeps realtime quote columns and favorite action working', async () => {
    mocks.updateWatchItem.mockResolvedValue({ ...watchItem, is_favorite: false });
    const page = await mountPage();
    expect(page.text()).toContain('12.00');
    expect(page.text()).toContain('多 2');
    await page.get('button[aria-label="取消特别关注"]').trigger('click');
    await flushPromises();
    expect(mocks.updateWatchItem).toHaveBeenCalledWith(11, { is_favorite: false });
  });

  it('combines code and name without a separate name column', async () => {
    const page = await mountPage();
    expect(page.get('thead').text()).toContain('股票');
    expect(page.get('thead').text()).not.toContain('名称');
    expect(page.get('tbody').text()).toContain('AAPL - Apple');
  });
});
