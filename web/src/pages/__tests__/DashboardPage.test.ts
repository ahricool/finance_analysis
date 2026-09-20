import { mount, flushPromises } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from '@/api';
import DashboardPage from '../DashboardPage.vue';
import { dashboardResponse } from '../../../tests/fixtures/dashboard';
import { useTimezoneStore } from '@/stores/timezoneStore';

vi.mock('@/api', () => ({ default: { get: vi.fn() } }));
const get = vi.mocked(apiClient.get);
function response(path: string, config?: { params?: Record<string, unknown> }) {
  const url = new URL(path, 'http://test');
  for (const [key, value] of Object.entries(config?.params ?? {})) if (value !== undefined) url.searchParams.set(key, String(value));
  return { data: dashboardResponse(url) };
}
async function render() {
  const pinia = createPinia();
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] });
  await router.push('/dashboard');
  const wrapper = mount(DashboardPage, { global: { plugins: [pinia, router] } });
  await flushPromises();
  return { wrapper, pinia };
}
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date('2026-09-09T08:00:00Z'));
  get.mockImplementation(async (path, config) => response(path, config));
});
afterEach(() => vi.useRealTimers());

describe('public market dashboard', () => {
  it('uses only public endpoints and preserves the API feed order including future events', async () => {
    const { wrapper } = await render();
    const paths = get.mock.calls.map(([path]) => path);
    expect(new Set(paths)).toEqual(new Set(['/api/v1/market-structure', '/api/v1/quant/signals/ranking', '/api/v1/etf-rotation/ranking', '/api/v1/trend-following/ranking', '/api/v1/crypto/btc/overview', '/api/v1/timeline']));
    expect(paths.join()).not.toMatch(/portfolio|holdings|watch-list|history|preferences/);
    expect(wrapper.get('[aria-label="Market Structure"]').text()).toContain('Breadth Divergence');
    expect(wrapper.get('[aria-label="Market Structure"]').text()).toContain('High Fragility Trends: 23');
    const feed = wrapper.findAll('[data-testid="dashboard-feed-item"]');
    expect(feed).toHaveLength(8);
    expect(feed.slice(0, 4).map(row => row.get('h3').text())).toEqual(['ORCL FY27 Q1 财报', '美国消费者价格指数 CPI', 'NVIDIA 上调 AI Server 需求预期', '科技板块继续强于大盘']);
    expect(feed[0]!.text()).toContain('$1.36');
    expect(wrapper.get('[aria-label="What\'s Next"]').text()).not.toContain('科技板块');
    expect(wrapper.text()).not.toContain('Ordinary Watch');
    const timelineCalls = get.mock.calls.filter(([path]) => path === '/api/v1/timeline');
    expect(timelineCalls[0]![1]?.params).toEqual({ limit: 10, timezone: 'Asia/Shanghai' });
    expect(timelineCalls[1]![1]?.params).toMatchObject({ end_date: '2026-09-16', category: 'event' });
    for (const path of ['/timeline', '/crypto/btc', '/research/quant?market=CN', '/research/quant?market=US', '/research/etf-rotation?market=CN', '/research/trend-following?market=CN']) expect(wrapper.find(`a[href="${path}"]`).exists()).toBe(true);
    wrapper.unmount();
  });

  it('shows unscaled Trend scores, breakdowns and dates before strategy changes and model signals', async () => {
    const { wrapper } = await render();
    const regime = wrapper.get('[aria-label="Market Regime"]');
    expect(regime.text()).toContain('市场环境 / MARKET REGIME');
    for (const text of ['RISK ON', 'NEUTRAL', '72.4', '53.2', '趋势 76', '宽度 71', '风险 68',
      '趋势 56', '宽度 51', '风险 48', '数据日期 2026-09-18', '数据日期 2026-09-17']) {
      expect(regime.text()).toContain(text);
    }
    expect(regime.text()).not.toMatch(/7240|5320/);
    expect(wrapper.text()).not.toMatch(/最大风险敞口|MARKET PULSE/);
    expect(wrapper.findAll('section').map(section => section.attributes('aria-label'))).toEqual([
      'Market Structure', 'Market Regime', "What's Changed", 'Latest', "What's Next", 'Model Pulse',
    ]);
    const model = wrapper.get('[aria-label="Model Pulse"]');
    expect(model.text()).toContain('Research Signal');
    expect(model.text()).toContain('中际旭创');
    expect(model.text()).toContain('NVIDIA');
    expect(model.text()).not.toMatch(/RISK ON|NEUTRAL/);
    for (const path of ['/api/v1/trend-following/ranking', '/api/v1/quant/signals/ranking']) {
      expect(get.mock.calls.filter(([url]) => url === path).map(([, config]) => config?.params.market)).toEqual(['CN', 'US']);
    }
    wrapper.unmount();
  });

  it.each(['CN', 'US'])('isolates and retries a failed %s Trend resource shared by regime and changes', async market => {
    get.mockImplementation(async (path, config) => {
      if (path.includes('trend-following') && config?.params?.market === market) throw new Error('unavailable');
      return response(path, config);
    });
    const { wrapper } = await render();
    const regime = wrapper.get('[aria-label="Market Regime"]');
    expect(regime.text()).toContain('暂时无法获取');
    expect(regime.text()).toContain(market === 'CN' ? '53.2' : '72.4');
    const changes = wrapper.get('[aria-label="What\'s Changed"]');
    if (market === 'US') {
      await changes.findAll('button').find(button => button.text() === '美股')!.trigger('click');
    }
    expect(changes.text()).toContain('暂时无法获取');
    expect(wrapper.get('[aria-label="Model Pulse"]').text()).toContain('NVIDIA');
    expect(wrapper.get('[aria-label="Market Structure"]').text()).toContain('Breadth Divergence');
    expect(wrapper.findAll('[data-testid="dashboard-feed-item"]')).toHaveLength(8);
    const callsBefore = get.mock.calls.length;
    get.mockImplementation(async (path, config) => response(path, config));
    await regime.get('button').trigger('click');
    await flushPromises();
    expect(get.mock.calls.slice(callsBefore)).toEqual([
      ['/api/v1/trend-following/ranking', { params: { market, trade_date: undefined } }],
    ]);
    expect(regime.text()).not.toContain('暂时无法获取');
    expect(changes.text()).not.toContain('暂时无法获取');
    expect(regime.text()).toContain(market === 'CN' ? '72.4' : '53.2');
    wrapper.unmount();
  });

  it('keeps missing breakdown scores distinct from zero', async () => {
    get.mockImplementation(async (path, config) => {
      const result = response(path, config);
      return path.includes('trend-following') ? { data: { ...result.data, market_score: 0, score_breakdown: { trend: 0 } } } : result;
    });
    const { wrapper } = await render();
    const regime = wrapper.get('[aria-label="Market Regime"]');
    for (const text of ['0.0', '趋势 0', '宽度 —', '风险 —']) expect(regime.text()).toContain(text);
    wrapper.unmount();
  });

  it('isolates a failed ETF module and can retry it without clearing other sections', async () => {
    get.mockImplementation(async (path, config) => {
      if (path.includes('etf-rotation') && config?.params?.market === 'CN') throw new Error('unavailable');
      return response(path, config);
    });
    const { wrapper } = await render();
    expect(wrapper.text()).toContain('暂时无法获取');
    expect(wrapper.get('[aria-label="Market Regime"]').text()).toContain('RISK ON');
    expect(wrapper.findAll('[data-testid="dashboard-feed-item"]')).toHaveLength(8);
    expect(wrapper.text()).toContain('114,820');
    get.mockImplementation(async (path, config) => response(path, config));
    await wrapper.findAll('button').find(button => button.text() === '重试')!.trigger('click');
    await flushPromises();
    expect(wrapper.text()).not.toContain('暂时无法获取');
    wrapper.unmount();
  });

  it('renders loaded modules while one remains pending and refreshes timezone cutoffs', async () => {
    get.mockImplementation((path, config) => path.includes('trend-following') ? new Promise(() => {}) : Promise.resolve(response(path, config)));
    const { wrapper, pinia } = await render();
    expect(wrapper.get('[aria-label="Market Regime"]').findAll('[aria-label="正在加载"]')).toHaveLength(2);
    expect(wrapper.findAll('[data-testid="dashboard-feed-item"]')).toHaveLength(8);
    vi.setSystemTime(new Date('2026-09-09T01:00:00Z'));
    useTimezoneStore(pinia).setDisplayTimezone('America/New_York');
    await flushPromises();
    expect(get).toHaveBeenLastCalledWith('/api/v1/timeline', expect.objectContaining({ params: expect.objectContaining({ end_date: '2026-09-15', timezone: 'America/New_York' }) }));
    wrapper.unmount();
  });
});
