import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createMemoryHistory, createRouter } from 'vue-router';
import { createPinia } from 'pinia';
import type { Observation } from '@/api/marketSentiment';
import { toCamelCase } from '@/api/utils';
import MarketSentimentPage from '../MarketSentimentPage.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import SentimentCharts from '@/components/market-sentiment/SentimentCharts.vue';
import { pct, money } from '@/components/market-sentiment/display';
const api = vi.hoisted(() => ({ overview: vi.fn(), history: vi.fn(), pool: vi.fn(), ladder: vi.fn(), dates: vi.fn(), run: vi.fn() }));
vi.mock('@/api/marketSentiment', () => ({ marketSentimentApi: api }));
vi.mock('vue-echarts', () => ({ default: { template: '<div data-testid="chart" />' } }));
function observation(day = '2026-09-16'): Observation {
  return toCamelCase({ trade_date: day, previous_trade_date: '2026-09-15', rule_version: 'fa-market-sentiment-v1', scope: 'main',
    early_time_threshold: '10:00', state: 'UNKNOWN', heat_score: null, state_reasons: ['历史不足20日'],
    upstream_total: 2, excluded_st_count: 1, excluded_new_count: 1, excluded_union_count: 2, unknown_scope_count: 0,
    scope_complete: true, boards_complete: true, limit_up_count: 0, first_board_count: 0, multi_board_count: 0, highest_board: 0,
    board_distribution: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0, '6': 0, '7+': 0 }, unconfirmed_board_count: 0,
    early_limit_up_count: 0, valid_limit_up_time_count: 0, time_coverage: null, early_limit_up_ratio: null,
    seal_retention_median: null, valid_seal_retention_count: 0, seal_retention_coverage: null,
    seal_money_sum: 0, valid_seal_money_count: 0, seal_money_coverage: null, reasons: [],
    promotions: { '1_to_2': { source_date: '2026-09-15', target_date: day, complete: true, numerator: 0, denominator: 0, ratio: null, promoted_codes: [], not_promoted_codes: [] } },
    changes: {}, quality: { optional_errors: { limit_break: 'FuyaoError' } }, supplements: {},
    source_timestamp: '2026-09-16T07:00:00Z', fetched_at: '2026-09-16T11:20:00Z', generated_at: '2026-09-16T11:21:00Z',
  });
}
async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/research/market-sentiment', component: MarketSentimentPage }] });
  await router.push('/research/market-sentiment'); await router.isReady();
  return mount(MarketSentimentPage, { global: { plugins: [router, createPinia()] } });
}
beforeEach(() => {
  vi.resetAllMocks();
  api.overview.mockImplementation(async (day?: string) => ({ tradeDate: day || '2026-09-16', expectedTradeDate: '2026-09-16', observation: observation(day), industryTop: [] }));
  api.history.mockResolvedValue({ dates: ['2026-09-15', '2026-09-16'], items: [null, observation()] });
  api.dates.mockResolvedValue(['2026-09-16']); api.ladder.mockResolvedValue({ source: null });
  api.pool.mockResolvedValue({ available: true, kind: 'limit_up', total: 0, upstreamTotal: 2, page: 1, size: 50, items: [], basis: 'main' });
});
describe('Market Sentiment', () => {
  it('distinguishes real zero, null, partial availability and the upstream scope', async () => {
    const wrapper = await render(); await flushPromises();
    expect(wrapper.text()).toContain('上游全池 2');
    expect(wrapper.text()).toContain('数据不足');
    expect(wrapper.text()).toContain('局部未获取');
    expect(wrapper.text()).toContain('0 条符合当前筛选');
    expect(wrapper.text()).toContain('1→2：—（0/0）');
    expect(wrapper.text()).toContain('0.00万元');
    expect(wrapper.text()).toContain('不改变顶部与历史统计');
    expect(api.run).not.toHaveBeenCalled(); wrapper.unmount();
  });
  it('links chart dates to overview, pool and official ladder while keeping the history window', async () => {
    const wrapper = await render(); await flushPromises();
    wrapper.getComponent(SentimentCharts).vm.$emit('date', '2026-09-15'); await flushPromises();
    expect(api.overview).toHaveBeenLastCalledWith('2026-09-15');
    expect(api.pool).toHaveBeenLastCalledWith(expect.objectContaining({ trade_date: '2026-09-15' }));
    expect(api.ladder).toHaveBeenLastCalledWith('2026-09-15');
    expect(api.history).toHaveBeenCalledTimes(1); wrapper.unmount();
  });
  it('keeps explicitly missing dates missing without switching to latest', async () => {
    const wrapper = await render(); await flushPromises();
    api.overview.mockResolvedValueOnce({ tradeDate: '2026-09-14', expectedTradeDate: '2026-09-16', observation: null, industryTop: [] });
    wrapper.getComponent(AppDatePicker).vm.$emit('update:modelValue', '2026-09-14'); await flushPromises();
    expect(wrapper.get('[data-testid="sentiment-empty"]').text()).toContain('2026-09-14');
    expect(api.pool).toHaveBeenLastCalledWith(expect.objectContaining({ trade_date: '2026-09-14' })); wrapper.unmount();
  });
  it('limits reason filtering and all-record scope to the table', async () => {
    const wrapper = await render(); await flushPromises();
    wrapper.getComponent(SentimentCharts).vm.$emit('reason', 'A+B'); await flushPromises();
    expect(api.pool).toHaveBeenLastCalledWith(expect.objectContaining({ reason: 'A+B' }));
    await wrapper.get('input[type="checkbox"]').setValue(true); await flushPromises();
    expect(api.pool).toHaveBeenLastCalledWith(expect.objectContaining({ scope: 'all' }));
    expect(api.overview).toHaveBeenCalledTimes(1); wrapper.unmount();
  });
  it('optional pool failure leaves core observations visible', async () => {
    const wrapper = await render(); await flushPromises();
    api.pool.mockResolvedValueOnce({ available: false, kind: 'limit_break', total: null, upstreamTotal: null, items: [] });
    await wrapper.findAll('button').find(b => b.text().startsWith('炸板池'))!.trigger('click'); await flushPromises();
    expect(wrapper.text()).toContain('未获取'); expect(wrapper.text()).toContain('历史不足20日');
    expect(wrapper.text()).toContain('不推导炸板率'); wrapper.unmount();
  });
  it('ignores stale overview responses after a date change', async () => {
    let resolve!: (v: unknown) => void;
    api.overview.mockReturnValueOnce(new Promise(r => { resolve = r; }));
    const wrapper = await render(); await flushPromises();
    wrapper.getComponent(AppDatePicker).vm.$emit('update:modelValue', '2026-09-15'); await flushPromises();
    resolve({ tradeDate: '2026-09-16', observation: observation(), industryTop: [] }); await flushPromises();
    expect(wrapper.text()).toContain('数据有效日期 2026-09-15'); wrapper.unmount();
  });
  it('preserves percentage and money zero and does not coerce null', () => {
    expect(pct(0)).toBe('0.0%'); expect(pct(null)).toBe('—'); expect(money(0)).toBe('0.00万元');
    expect(toCamelCase({ promotions: { '1_to_2': 1 }, changes: { limit_up_count: 0 } })).toEqual({ promotions: { '1To2': 1 }, changes: { limitUpCount: 0 } });
  });
});
