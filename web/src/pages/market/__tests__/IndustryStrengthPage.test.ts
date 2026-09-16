import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createMemoryHistory, createRouter } from 'vue-router';
import { createPinia } from 'pinia';
import type { IndustrySnapshot } from '@/api/industryStrength';
import { toCamelCase } from '@/api/utils';
import IndustryStrengthPage from '../IndustryStrengthPage.vue';
const api = vi.hoisted(() => ({ ranking: vi.fn(), dates: vi.fn(), history: vi.fn(), detail: vi.fn(), constituents: vi.fn() }));
vi.mock('@/api/industryStrength', () => ({ industryStrengthApi: api }));
vi.mock('vue-echarts', () => ({ default: { template: '<div data-testid="chart" />' } }));
function row(code = '881101.TI', name = '行业甲', rank = 1): IndustrySnapshot {
  return { tradeDate: '2026-09-16', industryCode: code, industryName: name, state: 'STRONG', close: 100,
    strengthRank: rank, strengthScore: 90 - rank, ret1D: .01, ret5D: .03, ret10D: .04, ret20D: .05,
    rs5D: .01, rs10D: .02, rs20D: .03, rankChange1D: 2, rankChange3D: 5, rankChange5D: null,
    previous5DReturn: .01, momentumAcceleration5D: .02, accelerationPercentile: 80, turnoverRatio5D: 1.2,
    upRatio: .7, aboveMa5Ratio: .8, aboveMa20Ratio: .9, equalWeightReturn: .01,
    constituentCount: 10, validConstituentCount: 10, upCount: 7, downCount: 2, flatCount: 1,
    dataTimestamp: '2026-09-16T07:00:00Z', membersObservedAt: '2026-09-16T11:00:00Z',
    createdAt: '2026-09-16T11:05:00Z', updatedAt: '2026-09-16T11:05:00Z',
    quality: { catalogCount: 2, rankedCount: 2, coverage: 1, excluded: {} } };
}
const rows = [row(), row('881102.TI', '行业乙', 2)];
async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/research/industry-strength', component: IndustryStrengthPage }] });
  await router.push('/research/industry-strength');
  await router.isReady();
  return mount(IndustryStrengthPage, { global: { plugins: [router, createPinia()] } });
}
beforeEach(() => {
  vi.clearAllMocks();
  api.ranking.mockResolvedValue({ tradeDate: '2026-09-16', expectedTradeDate: '2026-09-16', items: rows });
  api.dates.mockResolvedValue(['2026-09-16', '2026-09-15']);
  api.history.mockResolvedValue({ dates: ['2026-09-16'], items: rows });
  api.detail.mockImplementation(async (code: string) => ({ current: rows.find(r => r.industryCode === code), history: rows.filter(r => r.industryCode === code) }));
  api.constituents.mockResolvedValue({ tradeDate: '2026-09-16', membersObservedAt: '2026-09-16T11:00:00Z', constituentCount: 0, validConstituentCount: 0, items: [] });
});
describe('Industry Strength', () => {
  it('renders loading then rankings, semantics and charts', async () => {
    let resolve!: (value: unknown) => void;
    api.ranking.mockReturnValueOnce(new Promise(r => { resolve = r; }));
    const wrapper = await render();
    expect(wrapper.find('[data-testid="industry-loading"]').exists()).toBe(true);
    resolve({ tradeDate: '2026-09-16', expectedTradeDate: '2026-09-16', items: rows }); await flushPromises();
    expect(wrapper.find('[data-testid="industry-ranking"]').exists()).toBe(true);
    expect(wrapper.text()).toContain('当前成分股不代表历史成分');
    expect(wrapper.text()).toContain('不代表行业指数贡献');
    expect(wrapper.findAll('[data-testid="chart"]')).toHaveLength(2);
    wrapper.unmount();
  });
  it('renders explicit empty state without requesting live constituents', async () => {
    api.ranking.mockResolvedValue({ items: [], tradeDate: null });
    const wrapper = await render(); await flushPromises();
    expect(wrapper.find('[data-testid="industry-empty"]').exists()).toBe(true);
    expect(api.constituents).not.toHaveBeenCalled(); wrapper.unmount();
  });
  it('shows API failure and retry', async () => {
    api.ranking.mockRejectedValue(new Error('offline'));
    const wrapper = await render(); await flushPromises();
    expect(wrapper.text()).toContain('重新加载');
    expect(wrapper.find('[data-testid="industry-ranking"]').exists()).toBe(false); wrapper.unmount();
  });
  it('selects industries and sorts table', async () => {
    const wrapper = await render(); await flushPromises();
    const button = wrapper.get('[data-testid="industry-ranking"]').findAll('button').find(b => b.text() === '行业乙')!;
    await button.trigger('click'); await flushPromises();
    expect(api.detail).toHaveBeenLastCalledWith('881102.TI', '2026-09-16');
    expect(api.constituents).toHaveBeenLastCalledWith('881102.TI');
    expect(wrapper.get('[data-testid="industry-detail"]').text()).toContain('行业乙');
    const rank = wrapper.findAll('button').find(b => b.text().startsWith('Rank'))!;
    await rank.trigger('click');
    expect(wrapper.get('tbody tr').text()).toContain('行业乙'); wrapper.unmount();
  });
  it('isolates constituent failures from saved history', async () => {
    api.constituents.mockRejectedValue(new Error('upstream unavailable'));
    const wrapper = await render(); await flushPromises();
    expect(wrapper.find('[data-testid="industry-detail"]').exists()).toBe(true);
    expect(wrapper.text()).toContain('重试当前成分'); wrapper.unmount();
  });
  it('ignores stale detail responses after changing industry', async () => {
    let resolve!: (value: unknown) => void;
    api.detail.mockReturnValueOnce(new Promise(r => { resolve = r; }));
    const wrapper = await render(); await flushPromises();
    await wrapper.get('[data-testid="industry-ranking"]').findAll('button').find(b => b.text() === '行业乙')!.trigger('click');
    await flushPromises(); resolve({ current: rows[0], history: [rows[0]] }); await flushPromises();
    expect(wrapper.get('[data-testid="industry-detail"]').text()).toContain('行业乙'); wrapper.unmount();
  });
  it('keeps numeric window casing in API conversion', () => {
    expect(toCamelCase({ rs_5d: .1, ret_10d: .2, above_ma5_ratio: .6, rank_change_3d: 1 }))
      .toEqual({ rs5D: .1, ret10D: .2, aboveMa5Ratio: .6, rankChange3D: 1 });
  });
});
