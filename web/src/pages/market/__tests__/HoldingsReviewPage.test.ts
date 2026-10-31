import { createPinia } from 'pinia';
import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useMarketStore } from '@/stores/marketStore';
import HoldingsReviewPage from '../HoldingsReviewPage.vue';
const api = vi.hoisted(() => ({ detail: vi.fn(), dates: vi.fn(), run: vi.fn() }));
vi.mock('@/api/holdingsReview', () => ({ holdingsReviewApi: api }));
const payload = () => ({
  today: '2026-10-30', requestedDate: '2026-10-30', previousTradeDate: '2026-10-29',
  scheduledAt: '2026-10-30T14:10:00+08:00', canRun: false,
  review: {
    id: 1, market: 'CN', tradeDate: '2026-10-30', status: 'completed', asOf: '2026-10-30T06:10:00Z',
    portfolio: { nav: 120000, cash: 30000, currency: 'CNY', valuationComplete: true },
    decision: { marketState: 'NEUTRAL', conclusion: '指数震荡，关注尾盘承接。', confidence: 'MEDIUM', degraded: false,
      sectors: [{ name: '半导体', strength: 'STRONG', rationale: '相对强度保持。' }],
      risks: [{ title: '尾盘波动', severity: 'MEDIUM', detail: '谨慎对待临时预演。' }], watchpoints: ['观察量能'],
      positions: [
        { positionId: '11', symbol: '600519.SH', action: 'BUY', changePct: 10, rationale: '已有持仓小幅加仓。', condition: '突破确认', invalidation: '跌破支撑', confidence: 'MEDIUM' },
        { positionId: '12', symbol: '510300.SH', action: 'HOLD', changePct: 0, rationale: '维持观察', condition: '', invalidation: '', confidence: 'MEDIUM' },
      ] },
    holdings: [
      { positionId: '11', accountId: '1', symbol: '600519.SH', name: '贵州茅台', quantity: 100, currentPrice: 120, averageCost: 100, unrealizedPnlPct: 20, weightPct: 10, todayBuyQuantity: 0 },
      { positionId: '12', accountId: '1', symbol: '510300.SH', name: '沪深300ETF', quantity: 500, currentPrice: null, averageCost: 4, unrealizedPnlPct: null, weightPct: null, todayBuyQuantity: 100 },
    ],
    indices: [{ symbol: '000300.SH', name: '沪深300', currentPrice: 4000, changePct: 1 }],
    research: { etfRotation: { status: 'available', observedAt: '2026-10-30T06:00:00Z', items: [{}] } },
    searchEvidence: { status: 'unverified', citations: [{ title: '伪来源', url: 'javascript:bad' }] },
    dataQuality: ['行业预演不可用'], markdown: '# 复盘',
  },
});
const render = () => mount(HoldingsReviewPage, { global: { plugins: [createPinia()], stubs: {
  StockLink: { props: ['code', 'name'], template: '<span>{{ name }} {{ code }}</span>' },
  AppDatePicker: { props: ['modelValue'], emits: ['update:modelValue'], template: '<input :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)" />' },
} } });
beforeEach(() => {
  vi.resetAllMocks();
  api.detail.mockResolvedValue(payload());
  api.dates.mockResolvedValue([{ tradeDate: '2026-10-30', status: 'completed' }, { tradeDate: '2026-10-29', status: 'completed' }]);
});
describe('private holdings review', () => {
  it('shows structured sections, frozen holdings, BUY as add, and data limits without unsafe links', async () => {
    const wrapper = render(); await flushPromises();
    expect(wrapper.text()).toContain('指数震荡');
    expect(wrapper.text()).toContain('半导体');
    expect(wrapper.text()).toContain('贵州茅台');
    expect(wrapper.text()).toContain('加仓');
    expect(wrapper.text()).toContain('10% 当前持仓');
    expect(wrapper.text()).toContain('判断失效');
    expect(wrapper.text()).toContain('未取得可验证的搜索证据');
    expect(wrapper.find('a[href^="javascript:"]').exists()).toBe(false);
    const price = wrapper.findAll('thead th').find(h => h.text().includes('快照现价'))!;
    await price.get('button').trigger('click');
    expect(wrapper.findAll('[data-testid="review-position-row"]')[1]!.text()).toContain('沪深300ETF');
    await price.get('button').trigger('click');
    expect(wrapper.findAll('[data-testid="review-position-row"]')[1]!.text()).toContain('沪深300ETF');
    wrapper.unmount();
  });
  it('requests the selected history date without generating or recomputing results', async () => {
    const wrapper = render(); await flushPromises();
    await wrapper.get('input').setValue('2026-10-29'); await wrapper.get('input').trigger('change'); await flushPromises();
    expect(api.detail).toHaveBeenLastCalledWith('CN', '2026-10-29');
    expect(api.run).not.toHaveBeenCalled(); wrapper.unmount();
  });
  it('isolates late old-market responses and clears the selected date on market switch', async () => {
    let finish!: (value: unknown) => void;
    api.detail.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = render();
    api.detail.mockResolvedValue({ ...payload(), review: null });
    useMarketStore().market = 'US'; await flushPromises();
    finish(payload()); await flushPromises();
    expect(api.detail).toHaveBeenLastCalledWith('US', undefined);
    expect(wrapper.text()).not.toContain('贵州茅台');
    expect(wrapper.text()).toContain('所选日期暂无复盘'); wrapper.unmount();
  });
  it('shows failure without presenting an invented report', async () => {
    api.detail.mockResolvedValue({ ...payload(), review: { ...payload().review, status: 'failed', error: '数据采集失败', decision: null } });
    const wrapper = render(); await flushPromises();
    expect(wrapper.text()).toContain('数据采集失败');
    expect(wrapper.find('[data-testid="review-market-conclusion"]').exists()).toBe(false); wrapper.unmount();
  });
});

it('does not let a late run acknowledgement replace a newly selected history date', async () => {
  let finish!: (value: unknown) => void;
  api.detail.mockResolvedValue({ ...payload(), canRun: true, review: { ...payload().review, tradeDate: '2026-10-29' } });
  api.run.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const wrapper = render(); await flushPromises();
  const button = wrapper.findAll('button').find(b => b.text().includes('运行本日复盘'))!;
  await button.trigger('click');
  await wrapper.get('input').setValue('2026-10-29'); await wrapper.get('input').trigger('change'); await flushPromises();
  const count = api.detail.mock.calls.length;
  finish({ taskId: 'queued' }); await flushPromises();
  expect(api.detail.mock.calls.length).toBe(count);
  expect(api.detail).toHaveBeenLastCalledWith('CN', '2026-10-29');
  wrapper.unmount();
});
