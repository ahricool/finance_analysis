import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TrendMarket, TrendSnapshot } from '@/types/trendFollowing';
import { trendIndicatorDescriptions } from '@/components/trend-following/indicatorDescriptions';
import TrendFollowingPage from '../TrendFollowingPage.vue';

const apiMocks = vi.hoisted(() => ({ ranking: vi.fn(), candidates: vi.fn(), dates: vi.fn(), detail: vi.fn(), run: vi.fn() }));
vi.mock('@/api/trendFollowing', () => ({ trendFollowingApi: apiMocks }));
vi.mock('vue-sonner', () => ({ toast: { success: vi.fn() } }));
vi.mock('@/components/app/AppDatePicker.vue', () => ({
  default: {
    inheritAttrs: false, props: ['modelValue', 'label', 'availableDates', 'clearable', 'disabled'],
    emits: ['update:modelValue'],
    template: '<label>{{ label }}<input data-testid="trend-date-input" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" /></label>',
  },
}));

function snapshot(market: TrendMarket = 'CN'): TrendSnapshot {
  return {
    id: 1, market, tradeDate: '2026-08-28', code: market === 'CN' ? '000001.SZ' : 'AAPL.US',
    name: market === 'CN' ? '平安银行' : 'Apple', universeKey: market === 'CN' ? 'cn_csi300_csi500' : 'us_sp500',
    marketRegime: 'RISK_ON', marketScore: 82, rank: 1, trendScore: 80, rsScore: 78,
    breakoutScore: 76, alphaScore: 79, setup: 'BREAKOUT_55D', state: 'ENTRY', action: 'ENTRY',
    referencePrice: 110, atr: 2, signalDate: '2026-08-27', signalPrice: 108, openedAt: '2026-08-28',
    pendingAction: null, pendingSince: null, pendingRegime: null, pendingMaxExposure: null,
    lastAddPrice: 110, highestClose: 110, entryPrice: 110, initialStop: 106, trailingStop: 105,
    nextAddPrice: 111, exitLevel: 106, units: 1, suggestedInitialWeight: 0.1,
    suggestedMaxWeight: 0.1, reasons: ['candidate thresholds passed'], intradayConfirmation: 'UNAVAILABLE',
    scoreBreakdown: { trend: { weightedR2: 90 } }, generatedAt: '2026-08-28T12:00:00Z',
    features: {
      ma10: 108, ma20: 105, ma60: 100, ma20Slope: 0.01, trendCandidate: true,
      rawWeightedSlope: 0.01, weightedSlopePercentile: 95, weightedR2: 0.92,
      return20D: 0.12, return60D: 0.25, return20DPercentile: 90, return60DPercentile: 88,
      drawdown20D: -0.03, drawdown60D: -0.08, rs20D: 0.05, rs60D: 0.1,
      breakout20D: true, breakout55D: true, breakoutDistance: 0.01, volumeRatio: 1.5,
      distanceFromMa20: 0.04, priorCompression: true, compressionBreakout: true,
    },
  };
}

function ranking(market: TrendMarket) {
  return {
    market, tradeDate: '2026-08-28', universeKey: market === 'CN' ? 'cn_csi300_csi500' : 'us_sp500',
    benchmarkCode: market === 'CN' ? '510300.SH' : 'SPY.US', marketRegime: 'RISK_ON', marketScore: 82,
    suggestedMaxExposure: 1, universeSize: market === 'CN' ? 800 : 500, dataReadyCount: market === 'CN' ? 790 : 500,
    dataCoverage: market === 'CN' ? 0.9875 : 1, rankableCount: 480, candidateCount: 1,
    entryCount: 1, addCount: 0, holdCount: 0, reduceCount: 0, exitCount: 0, warnings: [],
    features: {}, scoreBreakdown: {}, generatedAt: '2026-08-28T12:00:00Z', items: [snapshot(market)],
  };
}

describe('TrendFollowingPage', () => {
  beforeEach(() => {
    apiMocks.dates.mockImplementation(async (market: TrendMarket) => ({ market, latest: '2026-08-28', items: ['2026-08-28'] }));
    apiMocks.ranking.mockImplementation(async (market: TrendMarket) => ranking(market));
    apiMocks.candidates.mockImplementation(async (market: TrendMarket) => ({ market, tradeDate: '2026-08-28', summary: ranking(market), items: [snapshot(market)] }));
    apiMocks.detail.mockImplementation(async (_code: string, market: TrendMarket) => ({ market,
      metadata: { market, code: snapshot(market).code, name: snapshot(market).name }, latest: snapshot(market),
      history: [snapshot(market)], marketContext: ranking(market),
    }));
    apiMocks.run.mockResolvedValue({ taskId: 'task-1', status: 'pending', market: 'CN', tradeDate: null });
  });
  afterEach(() => { document.body.innerHTML = ''; vi.clearAllMocks(); });

  it('renders CN scope, regime, ranking, state and action on mobile-safe layout', async () => {
    const wrapper = mount(TrendFollowingPage, { attachTo: document.body });
    await flushPromises();
    expect(wrapper.text()).toContain('沪深300 + 中证500');
    expect(wrapper.text()).toContain('RISK_ON');
    expect(wrapper.text()).toContain('平安银行');
    expect(wrapper.text()).toContain('建议入场');
    expect(wrapper.find('table').classes().join(' ')).toContain('min-w-');
    expect(wrapper.find('[aria-label="查看 Market Score 指标说明与计算公式"]').exists()).toBe(true);
    expect(wrapper.find('[aria-label="查看 Alpha 指标说明与计算公式"]').exists()).toBe(true);
  });

  it('documents explanations and formulas for trend-following key indicators', () => {
    expect(trendIndicatorDescriptions.alpha).toContain('综合 Alpha 分');
    expect(trendIndicatorDescriptions.alpha).toContain('0.35×Trend');
    expect(trendIndicatorDescriptions.trend).toContain('趋势分');
    expect(trendIndicatorDescriptions.trend).toContain('0.30×clamp(SlopePct)');
    expect(trendIndicatorDescriptions.relativeStrength).toContain('RS =');
    expect(trendIndicatorDescriptions.atr).toContain('ATR20 = Mean(TR, 20)');
    expect(trendIndicatorDescriptions.initialWeight).toContain('0.5%');
  });

  it('keeps target-date data coverage separate from history coverage', () => {
    expect(trendIndicatorDescriptions.dataCoverage).toContain('只检查成分股在该日是否存在日线记录');
    expect(trendIndicatorDescriptions.dataCoverage).toContain('Data Coverage = DataReadyCount / UniverseSize');
    expect(trendIndicatorDescriptions.dataCoverage).toContain('不包含历史长度检查');
    expect(trendIndicatorDescriptions.dataCoverage).toContain('feature/history coverage 阶段单独检查');
    expect(trendIndicatorDescriptions.dataCoverage).not.toContain('当日收盘数据且历史长度足够');
  });

  it('documents candidate state and lifecycle action counts exactly', () => {
    expect(trendIndicatorDescriptions.candidate).toContain('Candidate = Count(State == "CANDIDATE")');
    expect(trendIndicatorDescriptions.candidate).toContain('不包含观察或持有状态');
    expect(trendIndicatorDescriptions.lifecycleCount).toContain('ENTRY = Count(Action == "ENTRY")');
    expect(trendIndicatorDescriptions.lifecycleCount).toContain('ADD = Count(Action == "ADD")');
    expect(trendIndicatorDescriptions.lifecycleCount).toContain('HOLD = Count(Action == "HOLD")');
    expect(trendIndicatorDescriptions.lifecycleCount).toContain('REDUCE = Count(Action == "REDUCE")');
    expect(trendIndicatorDescriptions.lifecycleCount).toContain('EXIT = Count(Action == "EXIT")');
  });

  it('documents the ValidSetup branch in breakout distance quality', () => {
    expect(trendIndicatorDescriptions.breakout).toContain('ValidSetup == false 时 DistanceQuality = 0');
    expect(trendIndicatorDescriptions.breakout).toContain('ValidSetup == true 时 DistanceQuality = clamp');
    expect(trendIndicatorDescriptions.breakout).toContain('BreakoutDistance×Close/max(ATR, 1e-12)−0.75');
  });

  it('preserves the exact exit comparison boundaries', () => {
    expect(trendIndicatorDescriptions.exitLevel).toContain('Close <= InitialStop');
    expect(trendIndicatorDescriptions.exitLevel).toContain('Close <= TrailingStop');
    expect(trendIndicatorDescriptions.exitLevel).toContain('Close < PreviousLow10');
    expect(trendIndicatorDescriptions.exitLevel).not.toContain('Close <= PreviousLow10');
  });

  it('switches to US S&P 500 snapshots', async () => {
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    await wrapper.get('[aria-label="市场"]').setValue('US');
    await flushPromises();
    expect(apiMocks.dates).toHaveBeenLastCalledWith('US');
    expect(apiMocks.ranking).toHaveBeenLastCalledWith('US', undefined);
    expect(wrapper.text()).toContain('S&P 500');
    expect(wrapper.text()).toContain('Apple');
  });

  it('opens detail sheet with risk metrics and history', async () => {
    mount(TrendFollowingPage, { attachTo: document.body });
    await flushPromises();
    (document.body.querySelector('[data-testid="trend-candidate"]') as HTMLElement).click();
    await flushPromises();
    expect(apiMocks.detail).toHaveBeenCalledWith('000001.SZ', 'CN', 60, '2026-08-28');
    expect(document.body.textContent).toContain('Alpha Score Breakdown');
    expect(document.body.textContent).toContain('理论风险权重');
    expect(document.body.textContent).toContain('Signal Date / Price');
    expect(document.body.textContent).toContain('Entry Date / Price');
    expect(document.body.querySelector('[data-testid="trend-history"]')).not.toBeNull();
  });

  it('runs latest data without sending the selected snapshot date', async () => {
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    await wrapper.get('[data-testid="trend-run-latest"]').trigger('click');
    await flushPromises();
    expect(apiMocks.run).toHaveBeenCalledWith('CN');
  });

  it('renders empty and error states', async () => {
    apiMocks.ranking.mockRejectedValueOnce(new Error('snapshot missing'));
    const errored = mount(TrendFollowingPage);
    await flushPromises();
    expect(errored.text()).toContain('snapshot missing');
    errored.unmount();
    apiMocks.ranking.mockResolvedValueOnce({ ...ranking('CN'), items: [] });
    apiMocks.candidates.mockResolvedValueOnce({ market: 'CN', tradeDate: '2026-08-28', summary: ranking('CN'), items: [] });
    const empty = mount(TrendFollowingPage);
    await flushPromises();
    expect(empty.text()).toContain('暂无趋势快照');
    expect(empty.text()).toContain('暂无策略候选');
  });
});
