import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it, vi } from 'vitest';
import BacktestDetailPage from '../BacktestDetailPage.vue';

const api = vi.hoisted(() => ({ run: vi.fn(), trades: vi.fn(), equity: vi.fn() }));
vi.mock('@/api/backtests', () => ({ backtestsApi: api }));

describe('BacktestDetailPage', () => {
  it('prominently displays the engine/version and raw-price warning', async () => {
    api.run.mockResolvedValue({
      id: 12, uid: 1, taskId: 'task', engine: 'rqalpha', engineVersion: '6.2.0', engineConfig: {},
      strategyKey: 'sma_cross', strategyName: '双均线策略', strategyVersion: '1.0.0', market: 'CN', symbolId: 1,
      code: '600519.SH', startDate: '2025-01-01', endDate: '2025-02-01', initialCash: 100000, benchmarkCode: null,
      parameters: { fastWindow: 5, slowWindow: 20 }, priceMode: 'raw', marketRuleVersion: '1.0.0', status: 'completed',
      progress: 100, summary: {}, warnings: [], error: null, createdAt: '2025-01-01T00:00:00Z', startedAt: null, finishedAt: null,
    });
    api.trades.mockResolvedValue([]); api.equity.mockResolvedValue([]);
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/market/backtests/:runId', component: BacktestDetailPage }, { path: '/market/backtests', component: { template: '<div />' } }] });
    await router.push('/market/backtests/12'); await router.isReady();
    const wrapper = mount(BacktestDetailPage, { global: { plugins: [router], stubs: { BacktestEquityChart: true, BacktestSummaryCards: true, BacktestTradeTable: true } } });
    await flushPromises();
    expect(wrapper.text()).toContain('RQAlpha · v6.2.0');
    expect(wrapper.text()).toContain('当前结果使用未复权价格');
  });
});
