import { mount, flushPromises } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { describe, expect, it, vi } from 'vitest';
import EarningsOutlookSummary from '../EarningsOutlookSummary.vue';
import EarningsOutlookDetail from '../EarningsOutlookDetail.vue';
import type { EarningsOutlook, EarningsDetail } from '@/api/timeline';
import { timelineApi } from '@/api/timeline';

vi.mock('@/api/timeline', () => ({ timelineApi: { earningsDetail: vi.fn(), refreshEarnings: vi.fn() } }));
const outlook: EarningsOutlook = {
  status: 'current', memberships: ['us_nasdaq100'], earningsHigh: true, reactionHigh: true,
  eps: { expectedValue: 1.2, judgment: 'beat', consensus: null },
  revenue: { expectedValue: 100, judgment: 'meet', consensus: null },
  earningsConfidence: 9, reactionConfidence: 8, responseDirection: 'down',
  expectedClose: 98, expectedReturnPct: -2, intradayLow: 95, intradayHigh: 103,
  targetTradingDate: '2026-10-05', provisional: false,
};

describe('Earnings confidence presentation', () => {
  it('shows two independent confidence labels and uses direction only for return color', () => {
    const wrapper = mount(EarningsOutlookSummary, { props: { outlook } });
    expect(wrapper.text()).toContain('财报判断高置信度 9/10');
    expect(wrapper.text()).toContain('首日走势高置信度 8/10');
    expect(wrapper.text()).toContain('模型证据评分，非胜率');
    expect(wrapper.get('.text-market-down').text()).toBe('-2.00%');
    expect(wrapper.text()).toContain('EPS beat');
  });
  it.each(['stale', 'frozen', 'superseded', 'ineligible'])('removes highlights for %s', status => {
    const wrapper = mount(EarningsOutlookSummary, { props: { outlook: { ...outlook, status } } });
    expect(wrapper.text()).not.toContain('高置信度');
    if (status === 'frozen') expect(wrapper.text()).toContain('公布前预测');
  });
  it('keeps stale applicable forecasts visible with phase and generation time but removes highlights', () => {
    const wrapper = mount(EarningsOutlookSummary, { props: { outlook: {
      ...outlook, freshness: 'stale', stage: 'near', generatedAt: '2026-10-01T20:10:00Z',
    } } });
    expect(wrapper.text()).toContain('当前前瞻');
    expect(wrapper.text()).toContain('资料待更新');
    expect(wrapper.text()).toContain('临近版 · 生成于');
    expect(wrapper.text()).toContain('预计收盘 $98.00');
    expect(wrapper.text()).not.toContain('高置信度');
  });
  it('keeps the legacy daily phase readable', () => {
    const wrapper = mount(EarningsOutlookSummary, { props: { outlook: {
      ...outlook, stage: 'daily', generatedAt: '2026-10-01T20:10:00Z',
    } } });
    expect(wrapper.text()).toContain('历史每日版');
  });
  it('does not highlight an unknown earnings judgment or provisional reaction', () => {
    const wrapper = mount(EarningsOutlookSummary, { props: { outlook: {
      ...outlook, eps: { ...outlook.eps!, judgment: 'unknown' }, provisional: true,
    } } });
    expect(wrapper.text()).not.toContain('高置信度');
  });
  it('shows a pending state without invented forecasts', () => {
    const wrapper = mount(EarningsOutlookSummary, { props: { outlook: {
      status: 'pending', memberships: ['us_nasdaq100'], earningsHigh: false, reactionHigh: false,
    } } });
    expect(wrapper.text()).toContain('待分析');
    expect(wrapper.text()).not.toContain('预计收盘');
  });
  it('loads research only in the detail component and preserves an empty-state explanation', async () => {
    vi.mocked(timelineApi.earningsDetail).mockResolvedValue({ status: 'pending', error: null, summary: null, actual: null, versions: [] });
    const wrapper = mount(EarningsOutlookDetail, { props: { eventId: 123 }, global: { plugins: [createPinia()] } });
    await flushPromises();
    expect(timelineApi.earningsDetail).toHaveBeenCalledWith(123);
    expect(wrapper.text()).toContain('暂无前瞻数据');
    expect(wrapper.text()).not.toContain('异步刷新前瞻');
    wrapper.unmount();
  });
});


describe('Price-only earnings review', () => {
  function detail(): EarningsDetail {
    return {
      status: 'frozen', error: null, summary: outlook,
      actual: {
        status: 'completed', reviewKind: 'price_v1', predictionId: 1, dailyReturnPct: 10,
        actualReturnPct: -1, closeError: -1, directionCorrect: false, rangeCovered: true,
        actual: { targetTradingDate: '2026-10-05', previousClose: 90,
          ohlc: { date: '2026-10-05', open: 100, high: 102, low: 95, close: 99 } },
      },
      versions: [{
        id: 1, stage: 'final', applicability: 'frozen', generatedAt: '2026-10-02T20:10:00Z',
        dataCutoff: '2026-10-02T20:10:00Z', releaseCutoff: '2026-10-05T12:00:00Z',
        model: 'test', backend: 'test', promptVersion: 'test', prediction: outlook,
        searchEvidence: { status: 'confirmed', requested: true, configuredSupport: true },
        research: { sources: [] },
      }],
    };
  }
  it('shows daily return separately from the frozen-reference prediction comparison', async () => {
    vi.mocked(timelineApi.earningsDetail).mockResolvedValue(detail());
    const wrapper = mount(EarningsOutlookDetail, { props: { eventId: 123 }, global: { plugins: [createPinia()] } });
    await flushPromises();
    const review = wrapper.get('[data-testid="earnings-price-review"]');
    expect(review.text()).toContain('已更新');
    expect(review.get('.text-market-up').text()).toBe('10.00%');
    expect(review.text()).toContain('相对原预测参考价涨跌 -1.00%');
    expect(review.text()).toContain('预测方向命中 否');
    expect(review.text()).not.toContain('EPS');
    expect(review.text()).not.toContain('营收');
    wrapper.unmount();
  });
  it('shows waiting for prices without fabricating returns or a successful match', async () => {
    const data = detail();
    data.actual = { status: 'pending', reviewKind: 'price_v1', predictionId: 1,
      actual: { ohlc: null, missingReason: '等待目标交易日收盘' } };
    vi.mocked(timelineApi.earningsDetail).mockResolvedValue(data);
    const wrapper = mount(EarningsOutlookDetail, { props: { eventId: 123 }, global: { plugins: [createPinia()] } });
    await flushPromises();
    const review = wrapper.get('[data-testid="earnings-price-review"]');
    expect(review.text()).toContain('等待收盘或日线');
    expect(review.text()).toContain('预测方向命中 —');
    expect(review.text()).not.toContain('已更新');
    wrapper.unmount();
  });
});
