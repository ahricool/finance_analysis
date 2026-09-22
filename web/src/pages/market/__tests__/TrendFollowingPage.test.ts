import { marketDataApi } from '@/api/marketData';
import TrendFragilityHistoryChart from '@/components/trend-following/TrendFragilityHistoryChart.vue';
import TrendRankHistoryChart from '@/components/trend-following/TrendRankHistoryChart.vue';
import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TrendMarket, TrendSnapshot, TrendRankingSnapshot, TrendRankingResponse } from '@/types/trendFollowing';
import { trendIndicatorDescriptions } from '@/components/trend-following/indicatorDescriptions';
import TrendFollowingPage from '../TrendFollowingPage.vue';

const apiMocks = vi.hoisted(() => ({
  transitions: vi.fn(), breadthHistory: vi.fn(), ranking: vi.fn(), candidates: vi.fn(), dates: vi.fn(), detail: vi.fn(), detailHistory: vi.fn(), run: vi.fn(), preview: vi.fn(), previewStatus: vi.fn(),
}));
vi.mock('@/api/trendFollowing', () => ({ trendFollowingApi: apiMocks }));
vi.mock('vue-echarts', () => ({ default: { props: ['option'], template: '<div data-testid="rank-chart" />' } }));
vi.mock('@/api/marketData', () => ({ marketDataApi: { dailyBars: vi.fn().mockResolvedValue({ items: [] }) } }));

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
    breakoutScore: 76, alphaScore: 79, setup: 'BREAKOUT_20D', state: 'TRENDING',
    referencePrice: 110, atr: 2,



    reasons: ['candidate thresholds passed'],
    trendDurationDays: 12,
    scoreBreakdown: { trend: { weightedR2: 90 } }, generatedAt: '2026-08-28T12:00:00Z',
    features: {
      ma10: 108, ma20: 105, ma10Slope: 0.012, ma20Slope: 0.01, trendCandidate: true,
      rawWeightedSlope: 0.01, weightedSlopePercentile: 95, weightedR2: 0.92,
      return5D: 0.04, return10D: 0.08, return20D: 0.12,
      return10DPercentile: 92, return20DPercentile: 90,
      drawdown20D: -0.03, rs5D: 0.02, rs10D: 0.04, rs20D: 0.05,
      breakout10D: true, breakout20D: true, breakoutDistance: 0.01, volumeRatio: 1.5,
      distanceFromMa20: 0.04, priorCompression: true, compressionBreakout: true, trendResume: false,
    },
  };
}

function rankingSnapshot(market: TrendMarket = 'CN'): TrendRankingSnapshot {
  return { ...snapshot(market), rankChange1D: 5, rankChange3D: -2, rankChange5D: 0 };
}

function ranking(market: TrendMarket): TrendRankingResponse {
  return {
    market, tradeDate: '2026-08-28', universeKey: market === 'CN' ? 'cn_csi300_csi500' : 'us_sp500',
    benchmarkCode: market === 'CN' ? '510300.SH' : 'SPY.US', marketRegime: 'RISK_ON', marketScore: 82,
    universeSize: market === 'CN' ? 800 : 500, dataReadyCount: market === 'CN' ? 790 : 500,
    dataCoverage: market === 'CN' ? 0.9875 : 1, rankableCount: 480, candidateCount: 1,
    warnings: [],
    features: {}, scoreBreakdown: {}, generatedAt: '2026-08-28T12:00:00Z', items: [rankingSnapshot(market)],
    candidates: [snapshot(market)],
    changes: {
      previousTradeDate: '2026-08-27', marketScoreChange: 2.5, breadthScoreChange: 4,
      newCandidates: [], newWeakening: [], newBroken: [], transitions: [], movers: [],
    },
  };
}

function mockPreview(payload: Record<string, unknown> | null) {
  apiMocks.preview.mockResolvedValue(payload);
  const rows = payload?.snapshots ?? payload?.items;
  apiMocks.previewStatus.mockResolvedValue(payload ? {
    status: payload.status, market: payload.market, tradeDate: payload.tradeDate,
    previewTime: payload.previewTime, dataAsOf: payload.dataAsOf, provider: payload.provider,
    snapshotCount: Array.isArray(rows) ? rows.length : 0, warnings: payload.warnings ?? [],
  } : null);
}

describe('TrendFollowingPage', () => {
  beforeEach(() => {
    apiMocks.transitions.mockResolvedValue({ items: [], warnings: [] });
    apiMocks.breadthHistory.mockResolvedValue({ market: 'CN', dates: [], points: [], officialCount: 0, warnings: [] });
    apiMocks.dates.mockImplementation(async (market: TrendMarket) => ({ market, latest: '2026-08-28', items: ['2026-08-28'] }));
    apiMocks.ranking.mockImplementation(async (market: TrendMarket) => ranking(market));
    apiMocks.candidates.mockImplementation(async (market: TrendMarket) => ({ market, tradeDate: '2026-08-28', summary: ranking(market), items: [snapshot(market)] }));
    apiMocks.detail.mockImplementation(async (_code: string, market: TrendMarket) => ({ market,
      metadata: { market, code: snapshot(market).code, name: snapshot(market).name }, latest: snapshot(market),
      history: [snapshot(market)], marketContext: ranking(market),
    }));
    apiMocks.run.mockResolvedValue({ taskId: 'task-1', status: 'pending', market: 'CN', tradeDate: null });
    mockPreview(null);
  });
  afterEach(() => { document.body.innerHTML = ''; vi.clearAllMocks(); });

  it('keeps scoring groups separate from explain signals and blanks missing V2 qualities', async () => {
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    expect(wrapper.text()).toContain('Signals / Explain');
    expect(wrapper.text()).toContain('R² Quality');
    expect(wrapper.text()).toContain('Trend Contribution');
    expect(wrapper.get('[data-column="r2Quality"]').text()).toBe('—');
    expect(wrapper.get('[data-column="alphaTrendContribution"]').text()).toBe('—');
    expect(wrapper.get('[data-column="priorCompression"]').text()).toBe('是');
    expect(wrapper.get('[data-column="signedEfficiencyRatio10D"]').text()).toBe('—');
    wrapper.unmount();
  });

  it('shows em dashes for null ranking scalars and keeps them last in both sort directions', async () => {
    const high = { ...rankingSnapshot(), code: 'HIGH.US', name: 'High', rank: 1, trendScore: 90, rsScore: 80, atr: 3, referencePrice: 120, state: 'TRENDING' as const };
    const low = { ...rankingSnapshot(), code: 'LOW.US', name: 'Low', rank: 2, trendScore: 10, rsScore: 20, atr: 1, referencePrice: 80, state: 'CANDIDATE' as const };
    const missing = {
      ...rankingSnapshot(), code: 'MISSING.US', name: 'Missing', rank: 3,
      trendScore: null, rsScore: null, breakoutScore: null, atr: null, referencePrice: null, state: null, setup: null,
    };
    apiMocks.ranking.mockResolvedValueOnce({ ...ranking('CN'), items: [missing, low, high] });
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    const missingRow = wrapper.findAll('[data-testid="trend-row"]').find(row => row.text().includes('MISSING.US'))!;
    expect(missingRow.get('[data-column="trendScore"]').text()).toBe('—');
    expect(missingRow.get('[data-column="rsScore"]').text()).toBe('—');
    expect(missingRow.get('[data-column="atr"]').text()).toBe('—');
    expect(missingRow.get('[data-column="referencePrice"]').text()).toBe('—');
    expect(missingRow.get('[data-column="state"]').text()).toBe('—');
    expect(missingRow.text()).not.toContain('无明显趋势');
    const order = () => wrapper.findAll('[data-testid="trend-row"]').map(row => row.findAll('td')[1]!.find('span').text());
    const click = async (label: string) => {
      await wrapper.findAll('th button').find(button => button.text() === label)!.trigger('click');
    };
    await click('Trend Score');
    expect(order()).toEqual(['HIGH.US', 'LOW.US', 'MISSING.US']);
    await click('Trend Score');
    expect(order()).toEqual(['LOW.US', 'HIGH.US', 'MISSING.US']);
    await click('RS Score');
    expect(order()).toEqual(['HIGH.US', 'LOW.US', 'MISSING.US']);
    await click('RS Score');
    expect(order()).toEqual(['LOW.US', 'HIGH.US', 'MISSING.US']);
    wrapper.unmount();
  });

  it('opens ranking detail from keyboard and restores focus to the same row', async () => {
    const wrapper = mount(TrendFollowingPage, { attachTo: document.body });
    await flushPromises();
    const row = document.body.querySelector('[data-testid="trend-row"]') as HTMLElement;
    expect(row.tabIndex).toBe(0);
    row.focus();
    expect(document.activeElement).toBe(row);
    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    row.dispatchEvent(enter);
    expect(enter.defaultPrevented).toBe(true);
    await flushPromises();
    expect(document.body.querySelector('[data-testid="trend-detail"]')).not.toBeNull();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await flushPromises();
    expect(document.body.querySelector('[data-testid="trend-detail"]')).toBeNull();
    expect(document.activeElement).toBe(row);
    const space = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
    row.dispatchEvent(space);
    expect(space.defaultPrevented).toBe(true);
    await flushPromises();
    expect(document.body.querySelector('[data-testid="trend-detail"]')).not.toBeNull();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await flushPromises();
    expect(document.body.querySelector('[data-testid="trend-detail"]')).toBeNull();
    expect(document.activeElement).toBe(row);
    wrapper.unmount();
  });

  it.each([
    ['pathScore', 'Path Score'], ['setupScore', 'Setup Score'], ['r2Quality', 'R² Quality'],
    ['concentrationQuality', 'Concentration Quality'], ['breakoutQuality', 'Breakout Quality'],
    ['alphaTrendContribution', 'Trend Contribution'], ['weightedSlopePercentile', 'Slope Percentile 15D'],
    ['rs10DQuality', 'RS 10D Quality'], ['drawdownQuality', 'Drawdown Quality'], ['trendCandidate', 'Trend Candidate'],
  ])('sorts all rows by %s without requesting detail', async (key, label) => {
    const items: TrendRankingSnapshot[] = Array.from({ length: 800 }, (_, index) => ({
      ...rankingSnapshot(), code: `V2${index}`, rank: index + 1,
      features: { ...rankingSnapshot().features, alphaVersion: 2,
        [key]: key === 'trendCandidate' ? index === 799 : key === 'drawdown20D' ? -index / 800 : index / 800 },
    }));
    items.push({ ...rankingSnapshot(), code: 'MISSING', rank: 801, features: {} });
    apiMocks.ranking.mockResolvedValueOnce({ ...ranking('CN'), items });
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    const header = wrapper.findAll('th button').find(button => button.text() === label)!;
    const highFirst = key === 'trendCandidate' ? 'V20' : 'V2799';
    const lowFirst = key === 'trendCandidate' ? 'V2799' : 'V20';
    await header.trigger('click');
    const first = () => wrapper.findAll('[data-testid="trend-row"]')[0]!;
    expect(first().text()).toContain(highFirst);
    expect(wrapper.findAll('[data-testid="trend-row"]').length).toBeLessThan(40);
    await header.trigger('click');
    expect(first().text()).toContain(lowFirst);
    expect(wrapper.findAll('[data-testid="trend-row"]').map(row => row.text()).join()).not.toContain('MISSING');
    expect(apiMocks.detail).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('shows V2 path explanation in the drawer and leaves missing historical metrics blank', async () => {
    const latest = snapshot();
    latest.scoreBreakdown = { alpha: { version: 2,
      components: { trend: 80, rs: 70, setup: 60, path: 90 },
      weights: { trend: .4, rs: .25, setup: .15, path: .2 },
      contributions: { trend: 32, rs: 17.5, setup: 9, path: 18 }, score: 76.5 } };
    latest.features = { ...latest.features, alphaVersion: 2, pathScore: 95.03, setupScore: 79.75,
      positiveReturnConcentration: .2857, atrExpansionRatio: 1.06, downsideControlQuality: 75.15,
      downsideUpsideRatio: .2857 };
    apiMocks.detail.mockResolvedValueOnce({ latest, history: [latest], metadata: latest, marketContext: ranking('CN') });
    const wrapper = mount(TrendFollowingPage, { attachTo: document.body });
    await flushPromises();
    expect(wrapper.get('[data-testid="trend-row"]').text()).toContain('V1');
    await wrapper.get('[data-testid="trend-row"]').trigger('click');
    await flushPromises();
    const detail = document.querySelector('[data-testid="trend-path-detail"]')!;
    expect(detail.textContent).toContain('Alpha V2');
    expect(detail.textContent).toContain('95.0');
    expect(detail.textContent).toContain('1.06');
    expect(document.querySelector('[data-testid="trend-alpha-contributions"]')!.textContent).toContain('32.0 分');
    wrapper.unmount();
  });

  it('virtualizes the full ranking without pagination and sorts the whole result', async () => {
    const items = Array.from({ length: 800 }, (_, index) => ({
      ...rankingSnapshot(), code: `STOCK${index}`, rank: index + 1, alphaScore: index / 8,
    }));
    apiMocks.ranking.mockResolvedValueOnce({ ...ranking('CN'), items });
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    expect(wrapper.findAll('[data-testid="trend-row"]')).toHaveLength(28);
    expect(wrapper.get('[data-testid="trend-ranking-count"]').text()).toContain('800');
    expect(wrapper.find('button[aria-label="下一页"]').exists()).toBe(false);
    const sort = wrapper.findAll('th button').find(button => button.text() === 'Alpha Score')!;
    await sort.trigger('click');
    expect(wrapper.findAll('[data-testid="trend-row"]')[0]!.text()).toContain('STOCK799');
    await wrapper.get('[data-testid="trend-ranking-search"]').setValue('stock700');
    expect(wrapper.findAll('[data-testid="trend-row"]')).toHaveLength(1);
    expect(wrapper.get('[data-testid="trend-row"]').text()).toContain('STOCK700');
    await wrapper.get('[data-testid="trend-ranking-search"]').setValue('不存在');
    expect(wrapper.findAll('[data-testid="trend-row"]')).toHaveLength(0);
    expect(wrapper.text()).toContain('没有匹配的股票');
    await wrapper.get('[data-testid="trend-ranking-search"]').setValue('平安银行');
    expect(wrapper.findAll('[data-testid="trend-row"]')).toHaveLength(28);
    expect(wrapper.get('[data-testid="trend-ranking-count"]').text()).toContain('800 / 800');
    expect(apiMocks.ranking).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it('filters by state on the full dataset before virtualization', async () => {
    const states = ['IDLE', 'WATCHING', 'CANDIDATE', 'TRENDING', 'WEAKENING', 'BROKEN'] as const;
    const items = Array.from({ length: 800 }, (_, index) => ({
      ...rankingSnapshot(),
      code: `STATE${index}`,
      name: `Stock ${index}`,
      rank: index + 1,
      alphaScore: index / 8,
      state: states[index % states.length],
    }));
    apiMocks.ranking.mockResolvedValueOnce({ ...ranking('CN'), items });
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    const click = async (label: string) => {
      await wrapper.findAll('[data-testid="trend-state-filter"] button').find(button => button.text() === label)!.trigger('click');
    };
    await click('趋势健康');
    expect(wrapper.get('[data-testid="trend-ranking-count"]').text()).toContain('133 / 800');
    expect(wrapper.findAll('[data-testid="trend-row"]')).toHaveLength(133);
    expect(wrapper.findAll('[data-testid="trend-row"]').every(row => row.text().includes('趋势健康'))).toBe(true);
    await wrapper.get('[data-testid="trend-ranking-search"]').setValue('state795');
    expect(wrapper.findAll('[data-testid="trend-row"]')).toHaveLength(1);
    expect(wrapper.get('[data-testid="trend-row"]').text()).toContain('STATE795');
    await wrapper.get('[data-testid="trend-ranking-search"]').setValue('');
    const sort = wrapper.findAll('th button').find(button => button.text() === 'Alpha Score')!;
    await sort.trigger('click');
    expect(wrapper.findAll('[data-testid="trend-row"]')[0]!.text()).toContain('STATE795');
    await click('趋势破坏');
    expect(wrapper.get('[data-testid="trend-ranking-count"]').text()).toContain('133 / 800');
    expect(wrapper.findAll('[data-testid="trend-row"]')[0]!.text()).toContain('STATE797');
    wrapper.unmount();
  });

  it('requests only the selected historical date and preserves it for detail and refresh', async () => {
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    apiMocks.ranking.mockClear();
    apiMocks.preview.mockClear();
    apiMocks.ranking.mockResolvedValueOnce({ ...ranking('CN'), tradeDate: '2026-08-27' });
    await wrapper.get('[data-testid="trend-date-input"]').setValue('2026-08-27');
    await flushPromises();
    expect(apiMocks.ranking.mock.calls).toEqual([['CN', '2026-08-27']]);
    expect(apiMocks.breadthHistory.mock.calls).toEqual([
      ['CN', '2026-08-28', false], ['CN', '2026-08-27', false],
    ]);
    expect(apiMocks.preview).not.toHaveBeenCalled();
    expect(apiMocks.candidates).not.toHaveBeenCalled();
    await wrapper.get('[data-testid="trend-row"]').trigger('click');
    await flushPromises();
    expect(apiMocks.detail).toHaveBeenLastCalledWith('000001.SZ', 'CN', 60, '2026-08-27');
    await wrapper.get('[data-testid="trend-refresh"]').trigger('click');
    await flushPromises();
    expect(apiMocks.ranking).toHaveBeenLastCalledWith('CN', '2026-08-27');
    wrapper.unmount();
  });

  it('requests rankings without waiting for the dates response', async () => {
    let resolveDates!: (value: { market: string; latest: string; items: string[] }) => void;
    apiMocks.dates.mockReturnValueOnce(new Promise(resolve => { resolveDates = resolve; }));
    const wrapper = mount(TrendFollowingPage);
    expect(apiMocks.ranking).toHaveBeenCalledWith('CN', undefined);
    resolveDates({ market: 'CN', latest: '2026-08-28', items: ['2026-08-28'] });
    await flushPromises();
    expect(wrapper.findAll('[data-testid="trend-row"]')).toHaveLength(1);
    wrapper.unmount();
  });

  it('sorts ranking locally in both directions and displays rank trends with nulls last', async () => {
    const a = { ...rankingSnapshot(), code: 'A.US', name: 'Alpha', rank: 1, alphaScore: 90, rankChange5D: 2 };
    const b = { ...rankingSnapshot(), code: 'B.US', name: 'Beta', rank: 2, alphaScore: 80, rankChange5D: null, rankChange3D: 7,
      features: { ...snapshot().features, return10D: 0.5 } };
    const c = { ...rankingSnapshot(), code: 'C.US', name: 'Gamma', rank: 3, alphaScore: 70,
      rankChange1D: null, rankChange3D: null, rankChange5D: null };
    apiMocks.ranking.mockResolvedValueOnce({ ...ranking('CN'), items: [b, c, a] });
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    const order = () => wrapper.findAll('[data-testid="trend-row"]').map(row => row.findAll('td')[1]!.find('span').text());
    const click = async (label: string) => {
      const button = wrapper.findAll('th button').find(button => button.text() === label)!;
      await button.trigger('click');
    };
    expect(order()).toEqual(['A.US', 'B.US', 'C.US']);
    await click('Alpha Rank');
    expect(order()).toEqual(['C.US', 'B.US', 'A.US']);
    for (const label of ['Alpha Score', '股票名称']) {
      await click(label);
      expect(order()).toEqual(['A.US', 'B.US', 'C.US']);
      await click(label);
      expect(order()).toEqual(['C.US', 'B.US', 'A.US']);
    }
    await wrapper.get('select[aria-label="排名排序指标"]').setValue('return10D');
    expect(order()[0]).toBe('B.US');
    await click('排名趋势');
    expect(order()).toEqual(['B.US', 'A.US', 'C.US']);
    await click('排名趋势');
    expect(order()).toEqual(['A.US', 'B.US', 'C.US']);
    expect(wrapper.find('[aria-sort="ascending"]').text()).toContain('排名趋势');
    const trends = wrapper.findAll('[data-testid="trend-rank-changes"]');
    expect(trends[0]!.text()).toContain('1D');
    expect(trends[0]!.text()).toContain('+5');
    expect(trends[0]!.find('.text-market-up').text()).toBe('+5');
    expect(trends[0]!.find('.text-market-down').text()).toBe('-2');
    expect(trends[0]!.text()).not.toMatch(/[↑↓→]/);
    expect(trends[0]!.text()).toContain('3D');
    expect(trends[0]!.text()).toContain('-2');
    expect(trends[0]!.text()).toContain('5D');
    expect(trends[2]!.text()).toContain('—');
    expect(apiMocks.ranking).toHaveBeenCalledTimes(1);
  });

  it('renders CN scope, regime, ranking, trend state in a compact desktop table', async () => {
    const wrapper = mount(TrendFollowingPage, { attachTo: document.body });
    await flushPromises();
    expect(wrapper.text()).toContain('沪深300 + 中证500');
    expect(wrapper.text()).toContain('RISK_ON');
    expect(wrapper.get('[data-testid="trend-rank-changes"]').text()).toContain('0');
    expect(wrapper.text()).toContain('平安银行');
    expect(wrapper.text()).toContain('趋势健康');
    expect(wrapper.find('table').classes()).toContain('w-full');
    expect(wrapper.findAll('[data-testid="trend-row"]')[0]!.findAll('td')).toHaveLength(wrapper.findAll('th[aria-sort]').length);
    expect(wrapper.text()).not.toContain('趋势观察');
    expect(wrapper.find('[data-testid="trend-candidate"]').exists()).toBe(false);
    expect(wrapper.find('[data-column="setupScore"]').exists()).toBe(true);
    expect(wrapper.find('[data-column="breakoutScore"]').exists()).toBe(false);
    expect(wrapper.text()).toContain('Lifecycle / Age');
    expect(wrapper.text()).toContain('12D');
    expect(wrapper.text()).toContain('Fragility');
    expect(wrapper.find('[aria-label="查看 Market Score 指标说明与计算公式"]').exists()).toBe(true);
    expect(wrapper.find('[aria-label="查看 Alpha Score 指标说明与计算公式"]').exists()).toBe(true);
  });

  it('renders market, lifecycle, transition and significant mover changes', async () => {
    const current = snapshot('CN');
    apiMocks.ranking.mockResolvedValueOnce({
      ...ranking('CN'),
      changes: {
        previousTradeDate: '2026-08-27',
        marketScoreChange: 2.5,
        breadthScoreChange: -1.5,
        newCandidates: [{ code: current.code, name: current.name, currentState: current.state, previousState: 'WATCHING', previousRank: 4,
          rankChange: 3, trendScoreChange: 4, rsScoreChange: 2, alphaScoreChange: 3 }],
        newWeakening: [], newBroken: [],
        transitions: [{ code: current.code, name: current.name, currentState: current.state, previousState: 'CANDIDATE', previousRank: 2,
          rankChange: 1, trendScoreChange: 2, rsScoreChange: 1, alphaScoreChange: 2 }],
        movers: [{ code: current.code, name: current.name, currentState: current.state, previousState: 'CANDIDATE', previousRank: 6,
          rankChange: 5, trendScoreChange: 7, rsScoreChange: 6, alphaScoreChange: 8 }],
      },
    });
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();

    expect(wrapper.get('[data-testid="trend-market-score-change"]').text()).toContain('+2.5');
    expect(wrapper.get('[data-testid="trend-breadth-score-change"]').text()).toContain('-1.5');
    expect(wrapper.get('[data-testid="trend-mover"]').text()).toContain('Trend +7.0');
    expect(wrapper.get('[data-testid="trend-mover"]').text()).toContain('RS +6.0');
    expect(wrapper.get('[data-testid="trend-changes-scroll"]').classes()).toEqual(
      expect.arrayContaining(['max-h-[32rem]', 'overflow-y-auto']),
    );
  });





  it('documents explanations and formulas for trend-following key indicators', () => {
    expect(trendIndicatorDescriptions.alpha).toContain('Alpha V2');
    expect(trendIndicatorDescriptions.alpha).toContain('0.40×Trend');
    expect(trendIndicatorDescriptions.trend).toContain('Momentum');
    expect(trendIndicatorDescriptions.trend).toContain('0.30×SlopePercentile');
    expect(trendIndicatorDescriptions.relativeStrength).toContain('RS =');
    expect(trendIndicatorDescriptions.weightedSlope).toContain('15 个交易日');
    expect(trendIndicatorDescriptions.slopePercentile).toContain('横截面百分位');
    expect(trendIndicatorDescriptions.slopePercentile).toContain('不是 raw slope');
    expect(trendIndicatorDescriptions.atr).toContain('ATR20 = Mean(TR, 20)');
  });

  it('keeps target-date data coverage separate from history coverage', () => {
    expect(trendIndicatorDescriptions.dataCoverage).toContain('只检查成分股在该日是否存在日线记录');
    expect(trendIndicatorDescriptions.dataCoverage).toContain('Data Coverage = DataReadyCount / UniverseSize');
    expect(trendIndicatorDescriptions.dataCoverage).toContain('不包含历史长度检查');
    expect(trendIndicatorDescriptions.dataCoverage).toContain('feature/history coverage 阶段单独检查');
    expect(trendIndicatorDescriptions.dataCoverage).not.toContain('当日收盘数据且历史长度足够');
  });

  it('documents candidate state conditions exactly', () => {
    expect(trendIndicatorDescriptions.candidate).toContain('CANDIDATE 状态数');
    expect(trendIndicatorDescriptions.candidate).toContain('不包含其他趋势状态');
  });

  it('documents continuous setup without boolean rewards', () => {
    expect(trendIndicatorDescriptions.breakout).toContain('max(0.85×B(z10),B(z20))');
    expect(trendIndicatorDescriptions.breakout).toContain('sigmoid(z/0.15)');
    expect(trendIndicatorDescriptions.path).toContain('Signed Efficiency 仅解释');
  });



  it('switches to US S&P 500 snapshots', async () => {
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    await wrapper.get('[aria-label="市场"] [role="radio"]').trigger('click');
    await flushPromises();
    expect(apiMocks.dates).toHaveBeenLastCalledWith('US');
    expect(apiMocks.ranking).toHaveBeenLastCalledWith('US', undefined);
    expect(apiMocks.breadthHistory.mock.calls).toEqual([
      ['CN', '2026-08-28', false], ['US', '2026-08-28', false],
    ]);
    expect(wrapper.text()).toContain('S&P 500');
    expect(wrapper.text()).toContain('Apple');
  });

  it('opens a centered dialog with ranking chart, risk metrics and history', async () => {
    mount(TrendFollowingPage, { attachTo: document.body });
    await flushPromises();
    (document.body.querySelector('[data-testid="trend-row"]') as HTMLElement).click();
    await flushPromises();
    expect(apiMocks.detail).toHaveBeenCalledWith('000001.SZ', 'CN', 60, '2026-08-28');
    expect(marketDataApi.dailyBars).toHaveBeenLastCalledWith('000001.SZ', '2026-08-28', undefined, expect.any(AbortSignal));
    const dialog = document.body.querySelector('[data-testid="trend-detail"]')!;
    expect(dialog.getAttribute('role')).toBe('dialog');
    expect(dialog.classList.contains('top-1/2')).toBe(true);
    expect(dialog.querySelector('[data-testid="trend-rank-history"]')).not.toBeNull();
    expect(dialog.querySelector('[data-testid="rank-chart"]')).not.toBeNull();
    expect(dialog.textContent).not.toContain('持续天数');
    expect(document.body.textContent).toContain('Alpha Score Breakdown');
    expect(document.body.textContent).toContain('Weighted slope 15D');
    expect(document.body.textContent).toContain('Return 5D / 10D / 20D');
    expect(document.body.textContent).toContain('10D / 20D Breakout');
    expect(document.body.textContent).not.toContain('55D');
    expect(document.body.textContent).not.toContain('60D');
    expect(document.body.querySelector('[data-testid="trend-history"]')).not.toBeNull();
  });

  it('runs latest data without sending the selected snapshot date', async () => {
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    await wrapper.get('[data-testid="trend-run-latest"]').trigger('click');
    await flushPromises();
    expect(apiMocks.run).toHaveBeenCalledWith('CN');
  });

  it('keeps every control in the snapshot action bar the same height', async () => {
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();

    const controls = [
      wrapper.get('[data-testid="trend-market"]'),
      wrapper.get('[data-testid="trend-refresh"]'),
      wrapper.get('[data-testid="trend-run-latest"]'),
    ];
    controls.forEach(control => expect(control.classes()).toContain('h-10'));
  });

  it('renders empty and error states', async () => {
    apiMocks.ranking.mockRejectedValueOnce(new Error('snapshot missing'));
    const errored = mount(TrendFollowingPage);
    await flushPromises();
    expect(errored.text()).toContain('snapshot missing');
    errored.unmount();
    apiMocks.ranking.mockResolvedValueOnce({ ...ranking('CN'), items: [], candidates: [] });
    apiMocks.candidates.mockResolvedValueOnce({ market: 'CN', tradeDate: '2026-08-28', summary: ranking('CN'), items: [] });
    const empty = mount(TrendFollowingPage);
    await flushPromises();
    expect(empty.text()).toContain('暂无趋势快照');
    expect(empty.text()).not.toContain('暂无策略候选');
    expect(empty.text()).not.toContain('趋势观察');
  });

  it('uses preview snapshots for ranking without a separate observation table', async () => {
    const previewSnap = {
      ...snapshot('CN'),
      tradeDate: '2026-09-10',
      name: '贵州茅台',
      code: '600519.SH',
      state: 'CANDIDATE' as const,

    };
    mockPreview({
      ...ranking('CN'),
      status: 'completed',
      tradeDate: '2026-09-10',
      previewTime: '2026-09-10T06:00:00Z',
      dataAsOf: '2026-09-10T05:59:00Z',
      provider: 'easyquotation_tencent',
      snapshots: [previewSnap],
    });
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();

    expect(apiMocks.preview).toHaveBeenCalledWith('CN');
    expect(apiMocks.breadthHistory.mock.calls).toEqual([['CN', undefined, true]]);
    expect(apiMocks.candidates).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="trend-row"]').text()).toContain('贵州茅台');
    expect(wrapper.get('[data-testid="trend-row"]').text()).toContain('趋势候选');
    expect(wrapper.find('[data-testid="trend-candidate"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="research-provider"]').text()).toBe('Tencent');
    expect(wrapper.find('[data-testid="trend-run-latest"]').exists()).toBe(false);
    await wrapper.get('[data-testid="research-mode-official"]').trigger('click');
    await flushPromises();
    expect(apiMocks.candidates).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="trend-run-latest"]').exists()).toBe(true);
  });

  it('keeps preview latest while loading official history for charts', async () => {
    const previewSnap = {
      ...snapshot('CN'),
      tradeDate: '2026-09-10',
      name: '贵州茅台',
      code: '600519.SH',
      alphaScore: 91,
      scoreBreakdown: { alpha: 91 },
      state: 'CANDIDATE' as const,

    };
    apiMocks.detailHistory.mockResolvedValue({ history: [snapshot('CN'), previewSnap] });
    mockPreview({
      ...ranking('CN'),
      status: 'completed',
      tradeDate: '2026-09-10',
      previewTime: '2026-09-10T06:00:00Z',
      dataAsOf: '2026-09-10T05:59:00Z',
      provider: 'easyquotation_tencent',
      snapshots: [previewSnap],
    });
    apiMocks.detail.mockResolvedValue({
      market: 'CN',
      metadata: { market: 'CN', code: '600519.SH', name: '贵州茅台' },
      latest: {
        ...snapshot('CN'), code: '600519.SH', name: '贵州茅台',
        alphaScore: 60, scoreBreakdown: { alpha: 60 }, state: 'WATCHING',
      },
      history: [snapshot('CN')],
      marketContext: ranking('CN'),
    });
    const wrapper = mount(TrendFollowingPage, { attachTo: document.body });
    await flushPromises();
    (document.body.querySelector('[data-testid="trend-row"]') as HTMLElement).click();
    await flushPromises();

    expect(apiMocks.detail).not.toHaveBeenCalled();
    expect(apiMocks.detailHistory).toHaveBeenCalledWith('600519.SH', 'CN', '2026-09-10');
    const dialog = document.body.querySelector('[data-testid="trend-detail"]')!;
    expect(dialog.textContent).toContain('"alpha": 91');
    expect(dialog.textContent).toContain('候选');
    expect(dialog.textContent).toContain('趋势健康');
    expect(dialog.textContent).not.toContain('"alpha": 60');
    expect(dialog.querySelector('[data-testid="trend-rank-history"]')).not.toBeNull();
    expect(dialog.querySelector('[data-testid="trend-history"]')).not.toBeNull();
    const chartHistory = wrapper.getComponent(TrendRankHistoryChart).props('history');
    expect(chartHistory.map(row => row.tradeDate)).toEqual(['2026-08-28', '2026-09-10']);
    expect(chartHistory.map(row => row.isPreview)).toEqual([false, true]);
    expect(wrapper.getComponent(TrendFragilityHistoryChart).props('history')).toEqual(chartHistory);
    expect(dialog.querySelector('[data-testid="trend-history"]')?.textContent).not.toContain('2026-09-10');

  });

  it('shows lifecycle with age and keeps age sorting in the ranking table', async () => {
    apiMocks.ranking.mockResolvedValueOnce({
      ...ranking('CN'),
      items: [
        { ...rankingSnapshot(), code: 'A.US', name: 'Alpha', rank: 1, trendDurationDays: 2 },
        { ...rankingSnapshot(), code: 'B.US', name: 'Beta', rank: 2, trendDurationDays: 12 },
        { ...rankingSnapshot(), code: 'C.US', name: 'Gamma', rank: 3, trendDurationDays: 0 },
        { ...rankingSnapshot(), code: 'D.US', name: 'Delta', rank: 4, trendDurationDays: null },
      ],
    });
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    const order = () => wrapper.findAll('[data-testid="trend-row"]').map(row => row.findAll('td')[1]!.find('span').text());
    const header = wrapper.findAll('th button').find(button => button.text().includes('Lifecycle / Age'));
    expect(header).toBeTruthy();
    expect(wrapper.text()).toContain('Lifecycle / Age');
    expect(wrapper.text()).toContain('12D');
    expect(wrapper.text()).toContain('Fragility');
    expect(order()).toEqual(['A.US', 'B.US', 'C.US', 'D.US']);
    await header!.trigger('click');
    expect(order()).toEqual(['B.US', 'A.US', 'C.US', 'D.US']);
    await header!.trigger('click');
    expect(order()).toEqual(['C.US', 'A.US', 'B.US', 'D.US']);
  });
  it('waits for an in-flight Preview when a transition opens detail without another download', async () => {
    const payload = { ...ranking('CN'), status: 'completed', previewTime: '2026-08-28T10:00:00Z',
      dataAsOf: null, provider: 'yfinance', snapshots: [snapshot()] };
    mockPreview(payload);
    let resolvePreview!: (value: typeof payload) => void;
    apiMocks.preview.mockReturnValueOnce(new Promise(resolve => { resolvePreview = resolve; }));
    apiMocks.detailHistory.mockResolvedValue({ history: [] });
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    const overview = wrapper.getComponent({ name: 'TrendMarketOverview' });
    // Deliver the transition click during the mode switch, before the loading render.
    void wrapper.get('[data-testid="research-mode-preview"]').trigger('click');
    overview.vm.$emit('select', { code: '000001.SZ', tradeDate: '2026-08-28', preview: true });
    await flushPromises();
    expect(apiMocks.preview).toHaveBeenCalledTimes(1);
    expect(apiMocks.detailHistory).not.toHaveBeenCalled();
    expect(document.body.querySelector('[data-testid="trend-detail"]')).not.toBeNull();
    resolvePreview(payload);
    await flushPromises();
    expect(document.body.querySelector('[data-testid="trend-detail"]')!.textContent).toContain('平安银行');
    expect(apiMocks.detailHistory).toHaveBeenCalledWith('000001.SZ', 'CN', '2026-08-28');
    expect(apiMocks.detail).not.toHaveBeenCalled();
    wrapper.getComponent({ name: 'TrendMarketOverview' }).vm.$emit('select', { code: '000001.SZ', tradeDate: '2026-08-28', preview: true });
    await flushPromises();
    expect(apiMocks.preview).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it('reports an explicit error when the loaded Preview has no matching transition stock', async () => {
    mockPreview({ ...ranking('CN'), status: 'completed', previewTime: '2026-08-28T10:00:00Z',
      dataAsOf: null, provider: 'yfinance', snapshots: [snapshot()] });
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    wrapper.getComponent({ name: 'TrendMarketOverview' }).vm.$emit('select', {
      code: 'MISSING.US', tradeDate: '2026-08-28', preview: true,
    });
    await flushPromises();
    const dialog = document.body.querySelector('[data-testid="trend-detail"]')!;
    expect(dialog.textContent).toContain('Preview 详情不可用');
    expect(dialog.textContent).toContain('当前 Preview 中未找到 MISSING.US');
    expect(apiMocks.preview).toHaveBeenCalledTimes(1);
    expect(apiMocks.detail).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('loads only status for official, lazily downloads Preview once, and refreshes the visible mode', async () => {
    mockPreview({ ...ranking('CN'), status: 'completed', previewTime: '2026-08-28T10:00:00Z', dataAsOf: null, provider: 'yfinance', snapshots: [snapshot()] });
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    expect(apiMocks.ranking).toHaveBeenCalledWith('CN', undefined);
    expect(apiMocks.previewStatus).toHaveBeenCalledTimes(1);
    expect(apiMocks.preview).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="research-data-mode-badge"]').text()).toContain('正式收盘');
    await wrapper.get('[data-testid="research-mode-preview"]').trigger('click');
    await flushPromises();
    expect(apiMocks.preview).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="research-provider"]').text()).toBe('Yahoo Finance');
    await wrapper.get('[data-testid="research-mode-official"]').trigger('click');
    await wrapper.get('[data-testid="trend-refresh"]').trigger('click');
    await flushPromises();
    expect(apiMocks.previewStatus).toHaveBeenCalledTimes(2);
    expect(apiMocks.preview).toHaveBeenCalledTimes(1);
    await wrapper.get('[data-testid="research-mode-preview"]').trigger('click');
    await flushPromises();
    expect(apiMocks.preview).toHaveBeenCalledTimes(1);
    await wrapper.get('[data-testid="trend-refresh"]').trigger('click');
    await flushPromises();
    expect(apiMocks.previewStatus).toHaveBeenCalledTimes(3);
    expect(apiMocks.preview).toHaveBeenCalledTimes(2);
    expect(apiMocks.breadthHistory).toHaveBeenCalledTimes(6);
    wrapper.unmount();
  });

  it.each(['failed', 'incomplete'])('shows %s Preview metadata without downloading rows', async (status) => {
    mockPreview({ ...{ ...ranking('CN'), status: 'completed', previewTime: '2026-08-28T10:00:00Z', dataAsOf: null, provider: 'yfinance', snapshots: [snapshot()] }, status, warnings: ['预演数据不完整'] });
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    expect(apiMocks.preview).not.toHaveBeenCalled();
    await wrapper.get('[data-testid="research-mode-preview"]').trigger('click');
    await flushPromises();
    expect(wrapper.get('[data-testid="research-preview-reason"]').text()).toContain('预演数据不完整');
    expect(apiMocks.preview).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('keeps the ranking and candidates when the breadth request fails', async () => {
    apiMocks.ranking.mockResolvedValue(ranking('CN'));
    apiMocks.dates.mockResolvedValue({ items: ['2026-08-28'] });
    apiMocks.previewStatus.mockResolvedValue(null);
    apiMocks.breadthHistory.mockRejectedValue(new Error('history failed'));
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    expect(wrapper.get('[data-testid="trend-breadth"]').text()).toContain('重试趋势广度');
    expect(wrapper.findAll('[data-testid="trend-row"]')).toHaveLength(1);
    expect(wrapper.text()).toContain('平安银行');
    wrapper.unmount();
  });

  it('opens the existing detail at the transition date instead of the selected table date', async () => {
    apiMocks.ranking.mockResolvedValue(ranking('CN'));
    apiMocks.dates.mockResolvedValue({ items: ['2026-08-28'] });
    apiMocks.previewStatus.mockResolvedValue(null);
    apiMocks.transitions.mockResolvedValue({ items: [], warnings: [] });
    apiMocks.breadthHistory.mockResolvedValue({ points: [], dates: [], officialCount: 0, warnings: [] });
    const wrapper = mount(TrendFollowingPage);
    await flushPromises();
    const overview = wrapper.findComponent({ name: 'TrendMarketOverview' });
    overview.vm.$emit('select', { code: '000001.SZ', tradeDate: '2026-08-27', preview: false });
    await flushPromises();
    expect(apiMocks.detail).toHaveBeenLastCalledWith('000001.SZ', 'CN', 60, '2026-08-27');
    expect(document.body.querySelector('[data-testid="trend-detail"]')).not.toBeNull();
    wrapper.unmount();
  });
  it('opens a dated official source link without switching to Preview', async () => {
    const { createMemoryHistory, createRouter } = await import('vue-router');
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/source', component: TrendFollowingPage }] });
    await router.push('/source?market=CN&symbol=000001.SZ&tradeDate=2026-08-28');
    await router.isReady();
    const wrapper = mount(TrendFollowingPage, { global: { plugins: [router] } });
    await flushPromises();
    expect(apiMocks.ranking).toHaveBeenCalledWith('CN', '2026-08-28');
    expect(apiMocks.detail).toHaveBeenCalledWith('000001.SZ', 'CN', 60, '2026-08-28');
    expect(apiMocks.preview).not.toHaveBeenCalled();
    wrapper.unmount();
  });

});
