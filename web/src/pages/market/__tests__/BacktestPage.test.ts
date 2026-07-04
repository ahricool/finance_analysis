import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BacktestPage from '../BacktestPage.vue';

const api = vi.hoisted(() => ({
  engines: vi.fn(), strategies: vi.fn(), symbols: vi.fn(), runs: vi.fn(), preflight: vi.fn(), create: vi.fn(),
}));
vi.mock('@/api/backtests', () => ({ backtestsApi: api }));

const engine = (key: 'backtrader' | 'rqalpha', order: number) => ({
  key, name: key === 'backtrader' ? 'Backtrader' : 'RQAlpha', description: key, displayOrder: order,
  isDefault: key === 'backtrader', recommended: key === 'backtrader', available: true,
  unavailableReason: null, version: key === 'backtrader' ? '1.9.78.123' : '6.2.0',
  supportedMarkets: key === 'backtrader' ? ['US', 'CN'] : ['CN'], supportedStrategies: ['sma_cross'],
});
const strategy = { key: 'sma_cross', name: '双均线策略', description: '', version: '1.0.0', frequency: '1d', supportedMarkets: ['US', 'CN'], supportedEngines: ['backtrader', 'rqalpha'], parameters: [{ key: 'fast_window', name: '快均线周期', type: 'integer', default: 5, minimum: 2, maximum: 120 }, { key: 'slow_window', name: '慢均线周期', type: 'integer', default: 20, minimum: 3, maximum: 250 }] };

beforeEach(() => {
  api.engines.mockResolvedValue([engine('rqalpha', 2), engine('backtrader', 1)]);
  api.strategies.mockResolvedValue([strategy]);
  api.symbols.mockImplementation(async (market: string) => market === 'US' ? [{ id: 1, market: 'US', code: 'AAPL.US', name: 'Apple', lotSize: null }] : [{ id: 2, market: 'CN', code: '600519.SH', name: '贵州茅台', lotSize: 100 }]);
  api.runs.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 });
});
afterEach(() => vi.useRealTimers());

describe('BacktestPage', () => {
  it('sorts and defaults to Backtrader, then refreshes strategies when RQAlpha is selected', async () => {
    const wrapper = mount(BacktestPage);
    await flushPromises();
    const cards = wrapper.find('[data-testid="backtest-engine-selector"]').findAll('button');
    expect(cards[0].text()).toContain('Backtrader');
    expect(cards[0].classes()).toContain('border-primary');
    await cards[1].trigger('click');
    await flushPromises();
    expect(api.strategies).toHaveBeenCalledWith('rqalpha');
    expect(wrapper.find('[data-testid="backtest-preflight"]').exists()).toBe(false);
  });

  it('clears its five-second polling timer when unmounted', async () => {
    vi.useFakeTimers();
    api.runs.mockResolvedValue({ items: [{ id: 1, status: 'processing' }], total: 1, page: 1, pageSize: 20 });
    const wrapper = mount(BacktestPage, { global: { stubs: { BacktestRunTable: true } } });
    await flushPromises();
    expect(vi.getTimerCount()).toBe(1);
    wrapper.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
