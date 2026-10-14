import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import BilingualLabel from '@/components/app/BilingualLabel.vue';
import { trendIndicatorDescriptions as descriptions } from '@/components/trend-following/indicatorDescriptions';
import { flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TrendDetailPanel from '../TrendDetailPanel.vue';
import ETFDetailPanel from '../ETFDetailPanel.vue';
import DailyKLineCard from '@/components/market-data/DailyKLineCard.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import TrendRankHistoryChart from '@/components/trend-following/TrendRankHistoryChart.vue';
import ETFRotationHistoryCharts from '@/components/etf-rotation/ETFRotationHistoryCharts.vue';

const mocks = vi.hoisted(() => ({
  trend: { detail: vi.fn(), previewDetail: vi.fn(), detailHistory: vi.fn() },
  etf: { detail: vi.fn(), previewDetail: vi.fn(), detailHistory: vi.fn() },
}));
vi.mock('@/api/trendFollowing', () => ({ trendFollowingApi: mocks.trend }));
vi.mock('@/api/etfRotation', () => ({ etfRotationApi: mocks.etf }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function snapshot(code = 'AAPL.US', tradeDate = '2026-09-10') {
  return { code, name: code, tradeDate, market: 'US', state: 'TRENDING', features: {}, scoreBreakdown: {},
    category: 'BROAD_INDEX', theme: 'GROWTH', riskGroup: 'EQUITY', rank: 1, alphaScore: 80, compositeScore: 82 };
}
function detail(code = 'AAPL.US', date = '2026-09-10') {
  const latest = snapshot(code, date);
  return { market: 'US', metadata: latest, latest, history: [latest], marketContext: null, marketSnapshot: null };
}

for (const kind of ['trend', 'etf'] as const) {
  describe(`${kind} detail panel`, () => {
    const component = kind === 'trend' ? TrendDetailPanel : ETFDetailPanel;
    const api = mocks[kind];
    const chart = kind === 'trend' ? TrendRankHistoryChart : ETFRotationHistoryCharts;
    const mountPanel = (context?: { tradeDate?: string; view?: 'official' | 'preview' }) => shallowMount(component, {
      props: { symbol: 'AAPL.US', market: 'US', context },
      global: { renderStubDefaultSlot: true },
    });
    beforeEach(() => {
      vi.resetAllMocks();
      api.detail.mockResolvedValue(detail());
      api.previewDetail.mockImplementation(async (_code: string, _market: string, date?: string) => {
        if (date && date !== '2026-09-10') throw { response: { status: 404 } };
        return detail();
      });
      api.detailHistory.mockResolvedValue({ history: [] });
    });

    it('loads latest official data from any entry and preserves historical chart context', async () => {
      const wrapper = mountPanel();
      await flushPromises();
      expect(api.detail).toHaveBeenCalledWith('AAPL.US', 'US', 60, undefined, ...(kind === 'trend' ? [20] : []));
      expect(api.previewDetail).not.toHaveBeenCalled();
      expect(wrapper.getComponent(DailyKLineCard).props('highlightDate')).toBe('2026-09-10');
      await wrapper.setProps({ context: { tradeDate: '2026-08-20', view: 'official' } });
      await flushPromises();
      expect(api.detail).toHaveBeenLastCalledWith('AAPL.US', 'US', 60, '2026-08-20', ...(kind === 'trend' ? [20] : []));
      await wrapper.setProps({ context: { tradeDate: '2026-08-20', view: 'official' } });
      await flushPromises();
      expect(api.detail).toHaveBeenCalledTimes(2);
      wrapper.unmount();
    });

    it('shows unsupported markets and missing snapshots neutrally', async () => {
      const wrapper = mountPanel();
      await flushPromises();
      await wrapper.setProps({ market: 'HK' });
      await flushPromises();
      expect(wrapper.text()).toContain('当前市场暂不支持');
      expect(api.detail).toHaveBeenCalledTimes(1);
      expect(wrapper.findComponent(DailyKLineCard).exists()).toBe(false);
      api.detail.mockRejectedValueOnce({ response: { status: 404, data: { detail: 'not found' } } });
      await wrapper.setProps({ market: 'CN' });
      await flushPromises();
      expect(wrapper.text()).toContain('暂无');
      expect(wrapper.findComponent(AppApiErrorAlert).exists()).toBe(false);
      wrapper.unmount();
    });

    it('loads preview independently, keeps it separate from formal history and retries history errors', async () => {
      api.detailHistory.mockRejectedValueOnce(new Error('history failed'));
      const wrapper = mountPanel({ view: 'preview', tradeDate: '2026-09-10' });
      await flushPromises();
      expect(api.detail).not.toHaveBeenCalled();
      expect(api.previewDetail).toHaveBeenCalledWith('AAPL.US', 'US', '2026-09-10', ...(kind === 'trend' ? [20] : []));
      expect(api.detailHistory).toHaveBeenCalledWith('AAPL.US', 'US', '2026-09-10', ...(kind === 'trend' ? [60, 20] : []));
      expect(wrapper.text()).toContain('当前详情为 Preview');
      expect(wrapper.findComponent(DailyKLineCard).exists()).toBe(true);
      api.detailHistory.mockResolvedValueOnce({ history: [snapshot('AAPL.US', '2026-09-09'), snapshot()] });
      wrapper.getComponent(AppApiErrorAlert).vm.$emit('action');
      await flushPromises();
      expect(api.detailHistory).toHaveBeenCalledTimes(2);
      const history = wrapper.getComponent(chart).props('history');
      expect(history).toHaveLength(2);
      expect(history[0].tradeDate).toBe('2026-09-09');
      expect(history[1].isPreview).toBe(true);
      wrapper.unmount();
    });

    it('never substitutes a different preview date for pinned historical context', async () => {
      const wrapper = mountPanel({ view: 'preview', tradeDate: '2026-08-20' });
      await flushPromises();
      expect(wrapper.text()).toContain('暂无');
      expect(api.detailHistory).not.toHaveBeenCalled();
      expect(wrapper.findComponent(DailyKLineCard).exists()).toBe(false);
      wrapper.unmount();
    });

    it('ignores obsolete responses when symbol changes and offers an isolated detail retry', async () => {
      const stale = deferred<ReturnType<typeof detail>>();
      api.detail.mockReturnValueOnce(stale.promise);
      const wrapper = mountPanel();
      api.detail.mockRejectedValueOnce(new Error('request failed'));
      await wrapper.setProps({ symbol: 'MSFT.US' });
      await flushPromises();
      expect(wrapper.findComponent(AppApiErrorAlert).exists()).toBe(true);
      api.detail.mockResolvedValueOnce(detail('MSFT.US'));
      wrapper.getComponent(AppApiErrorAlert).vm.$emit('action');
      await flushPromises();
      stale.resolve(detail('AAPL.US'));
      await flushPromises();
      expect(wrapper.getComponent(DailyKLineCard).props('symbol')).toBe('MSFT.US');
      wrapper.unmount();
    });

    it('invalidates preview and history work after unmount or a newer context', async () => {
      const pending = deferred<ReturnType<typeof detail>>();
      api.previewDetail.mockReturnValueOnce(pending.promise);
      const closed = mountPanel({ view: 'preview' });
      closed.unmount();
      pending.resolve(detail());
      await flushPromises();
      expect(api.detailHistory).not.toHaveBeenCalled();
      const staleHistory = deferred<{ history: ReturnType<typeof snapshot>[] }>();
      api.detailHistory.mockReturnValueOnce(staleHistory.promise);
      const wrapper = mountPanel({ view: 'preview' });
      await flushPromises();
      await wrapper.setProps({ symbol: 'MSFT.US', context: { view: 'official' } });
      await flushPromises();
      staleHistory.reject(new Error('obsolete history failure'));
      await flushPromises();
      expect(wrapper.findComponent(AppApiErrorAlert).exists()).toBe(false);
      expect(wrapper.text()).not.toContain('正在加载正式历史');
      wrapper.unmount();
    });
  });
}


it('preserves trend duration, lifecycle, risk, box and mean-reversion hint descriptions', async () => {
  vi.resetAllMocks();
  mocks.trend.detail.mockResolvedValue({ ...detail(), latest: { ...snapshot(),
    features: { riskSizing: { suggestedPositionPct: .1, stopLossPct: .05, stopPrice: 90, riskBudgetPct: .01 } },
    fragilityBreakdown: { trendDecay: 10 },
  } });
  const wrapper = shallowMount(TrendDetailPanel, { props: { symbol: 'AAPL.US', market: 'US' }, global: { renderStubDefaultSlot: true } });
  await flushPromises();
  const actual = [...wrapper.findAllComponents(IndicatorHelpLabel), ...wrapper.findAllComponents(BilingualLabel)]
    .map(label => label.props().description);
  for (const key of ['trendDuration', 'lifecycle', 'fragility', 'trendAcceleration', 'signedEfficiency', 'riskStop', 'riskPosition',
    'boxState', 'boxQuality', 'boxWindowDays', 'boxHigh', 'boxLow', 'boxWidthPct', 'distanceToBoxHighPct', 'boxBreakoutDistanceAtr',
    'boxUpperTouches', 'boxLowerTouches', 'boxSlopeAtr', 'boxRSquared', 'boxOccupancy', 'boxAtr20', 'boxWidthQuality',
    'boxFlatnessQuality', 'boxOccupancyQuality', 'boxCompressionQuality', 'boxTouchQuality', 'mrState', 'mrQuality', 'rsi14', 'distanceFromMa20Atr']) {
    expect(descriptions[key], key).toBeTruthy();
    expect(actual, key).toContain(descriptions[key]);
  }
  wrapper.unmount();
});

it.each([40, 60] as const)('labels Entry evidence with the %s-session strategy windows', async period => {
  vi.resetAllMocks();
  const branch = { score: 80, qualityScore: 80, components: { distance: 80 },
    normalizedWeights: { distance: 1 }, contributions: { distance: 80 },
    checks: { ma20Rising: true, rs10Positive: true } };
  mocks.trend.detail.mockResolvedValue({ ...detail(), latest: { ...snapshot(),
    features: { entryBreakdown: { breakout: branch, resume: branch } },
  } });
  const wrapper = shallowMount(TrendDetailPanel, {
    props: { symbol: 'AAPL.US', market: 'US', context: { trendPeriod: period } },
    global: { renderStubDefaultSlot: true },
  });
  await flushPromises();
  expect(wrapper.text()).toContain(`MA${period} Distance Quality`);
  expect(wrapper.text()).toContain(`MA${period}上升: 通过`);
  expect(wrapper.text()).toContain(`RS${period / 2}为正: 通过`);
  expect(mocks.trend.detail).toHaveBeenCalledWith('AAPL.US', 'US', 60, undefined, period);
  wrapper.unmount();
});
