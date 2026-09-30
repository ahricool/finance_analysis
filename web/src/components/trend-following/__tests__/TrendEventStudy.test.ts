import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TrendEventStudy from '../TrendEventStudy.vue';
import { trendFollowingApi } from '@/api/trendFollowing';
import { exportExcel } from '@/utils/excelExport';
import type { EventStudyResponse, StrategyKey, StudyRegime } from '@/types/trendFollowing';
vi.mock('@/api/trendFollowing', () => ({ trendFollowingApi: { eventStudy: vi.fn() } }));
vi.mock('@/utils/excelExport', () => ({ exportExcel: vi.fn().mockResolvedValue(undefined) }));
vi.mock('vue-sonner', () => ({ toast: { error: vi.fn() } }));
const coverage = { featureCoverage: .5, featureSnapshotCount: 1, snapshotCount: 2,
  status: 'insufficient_feature_history' as const, continuousCompleteSince: '2026-09-01', incompleteDates: ['2026-08-28'] };
function response(regime: StudyRegime = 'ALL', strategy: StrategyKey | 'ALL' = 'ALL'): EventStudyResponse {
  return {
    market: 'CN', startDate: '2026-04-01', endDate: '2026-09-01', method: 'signal_close_v1', benchmark: '510300.SH', evaluatedAt: '',
    snapshotDates: ['2026-09-01'], missingSnapshotDates: [], boxFeatureCoverage: coverage, mrFeatureCoverage: coverage,
    groups: (['TREND_FOLLOWING', 'BOX_BREAKOUT', 'PULLBACK_RESUME', 'MEAN_REVERSION'] as const).map((s, i) => ({
      ...coverage, strategy: s, regime, eventCount: 10 + i, excursionCount: 5,
      horizons: [5, 10, 20].map(days => ({ days, maturedCount: 5, excessMaturedCount: 4, pendingCount: 3, missingCount: 2,
        meanReturn: .02, medianReturn: .01, winRate: .6, meanExcessReturn: .01, medianExcessReturn: 0, excessWinRate: .5 })),
      mfe20: { mean: .08, median: .06 }, mae20: { mean: -.05, median: -.04 },
    })),
    eventCount: 1, offset: 0, limit: 100,
    events: [{ market: 'CN', tradeDate: '2026-09-01', code: '000001.SZ', name: '历史样本', strategy: strategy === 'ALL' ? 'BOX_BREAKOUT' : strategy,
      regime: 'RISK_OFF', signalPrice: 100, evaluationBasePrice: 100, context: { boxQuality: 85, boxWindowDays: 30, boxWidthPct: .08, boxBreakoutDistanceAtr: .4 },
      horizons: [5, 10, 20].map(days => ({ days, targetDate: '2026-09-30', status: days === 20 ? 'pending' : 'available', value: days === 20 ? null : .02,
        benchmarkStatus: 'missing', benchmarkReturn: null, excessStatus: 'missing', excessReturn: null })),
      excursionStatus: 'pending', observedSessions: 10, missingDates: [], mfe20: null, mae20: null }],
  };
}
describe('TrendEventStudy', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(trendFollowingApi.eventStudy).mockImplementation(async (_market, _start, _end, regime, strategy) => response(regime, strategy));
  });
  it('shows aggregates, sample denominators, frozen context and data statuses', async () => {
    const wrapper = mount(TrendEventStudy, { props: { market: 'CN', endDate: '2026-09-01' } });
    await flushPromises();
    expect(wrapper.findAll('[data-testid="study-strategy-row"]')).toHaveLength(4);
    expect(wrapper.text()).toContain('insufficient_feature_history');
    expect(wrapper.text()).toContain('Box 连续完整自 2026-09-01');
    expect(wrapper.text()).toContain('MR 连续完整自 2026-09-01');
    expect(wrapper.text()).not.toContain('最早完整日期');
    expect(wrapper.text()).toContain('不代表能按 T 收盘价真实成交');
    await wrapper.findAll('[data-testid="study-strategy-row"]').find(r => r.text().includes('箱体突破'))!.trigger('click');
    await flushPromises();
    expect(wrapper.get('[data-testid="study-event-row"]').text()).toContain('历史样本');
    expect(wrapper.get('[data-testid="study-event-row"]').text()).toContain('Quality: 85.00');
    expect(wrapper.text()).toContain('未到期');
    expect(wrapper.text()).toContain('缺行情');
    expect(wrapper.text()).toContain('RISK_OFF');
    expect(wrapper.text()).toContain('中位超额');
    wrapper.unmount();
  });
  it('updates CN/US, date range and regime, resets drilldown and sorts all columns', async () => {
    const wrapper = mount(TrendEventStudy, { props: { market: 'CN', endDate: '2026-09-01' } });
    await flushPromises();
    await wrapper.findAll('th').find(th => th.text() === 'N')!.get('button').trigger('click');
    expect(wrapper.findAll('[data-testid="study-strategy-row"]')[0]!.text()).toContain('超跌反弹');
    await wrapper.setProps({ market: 'US' });
    await wrapper.get('[aria-label="研究开始日期"]').setValue('2026-08-01');
    await wrapper.get('[aria-label="研究市场环境"]').setValue('RISK_ON');
    await flushPromises();
    expect(trendFollowingApi.eventStudy).toHaveBeenLastCalledWith('US', '2026-08-01', '2026-09-01', 'RISK_ON', 'ALL', 0, expect.any(AbortSignal));
    await wrapper.findAll('button').find(b => b.text() === '导出汇总')!.trigger('click');
    await flushPromises();
    expect(exportExcel).toHaveBeenCalled();
    wrapper.unmount();
  });
  it('ignores an obsolete response after a market change', async () => {
    let resolve!: (data: EventStudyResponse) => void;
    vi.mocked(trendFollowingApi.eventStudy).mockReturnValueOnce(new Promise(r => { resolve = r; }));
    const wrapper = mount(TrendEventStudy, { props: { market: 'CN', endDate: '2026-09-01' } });
    await wrapper.setProps({ market: 'US' });
    await flushPromises();
    resolve({ ...response(), groups: [] });
    await flushPromises();
    expect(wrapper.findAll('[data-testid="study-strategy-row"]')).toHaveLength(4);
    wrapper.unmount();
  });
});
