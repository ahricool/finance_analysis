import { mount, flushPromises } from '@vue/test-utils';
import { createPinia } from 'pinia';
import { describe, expect, it, vi } from 'vitest';
import EarningsOutlookSummary from '../EarningsOutlookSummary.vue';
import EarningsOutlookDetail from '../EarningsOutlookDetail.vue';
import type { EarningsOutlook } from '@/api/timeline';
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
