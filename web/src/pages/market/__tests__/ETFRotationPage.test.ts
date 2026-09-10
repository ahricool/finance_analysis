import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ETFMarket, ETFMomentumSnapshot } from '@/types/etfRotation';
import { indicatorDescriptions } from '@/components/etf-rotation/indicatorDescriptions';
import ETFRotationPage from '../ETFRotationPage.vue';

const apiMocks = vi.hoisted(() => ({
  ranking: vi.fn(),
  candidates: vi.fn(),
  dates: vi.fn(),
  detail: vi.fn(),
  run: vi.fn(),
  preview: vi.fn(),
}));

vi.mock('@/api/etfRotation', () => ({
  etfRotationApi: apiMocks,
}));

vi.mock('vue-sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('@/components/app/AppDatePicker.vue', () => ({
  default: {
    inheritAttrs: false,
    props: ['modelValue', 'label', 'availableDates', 'clearable', 'disabled'],
    emits: ['update:modelValue'],
    template:
      '<label>{{ label }}<input data-testid="etf-rotation-date" type="text" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" /></label>',
  },
}));

vi.mock('@/components/etf-rotation/ETFRotationHistoryCharts.vue', () => ({
  default: { template: '<div data-testid="rotation-history-charts" />' },
}));

function snapshot(overrides: Partial<ETFMomentumSnapshot> = {}): ETFMomentumSnapshot {
  return {
    id: 1,
    market: 'CN',
    tradeDate: '2026-08-25',
    code: '588000.SH',
    name: '科创50ETF',
    category: 'BROAD_INDEX',
    theme: 'STAR50',
    riskGroup: 'BROAD_GROWTH',
    enabled: true,
    ret1D: 0.011,
    ret3D: 0.018,
    ret5D: 0.0234,
    ret10D: -0.012,
    ret20D: 0.04,
    rank1D: 4,
    rank3D: 2,
    rank5D: 3,
    rank10D: 5,
    rank20D: 6,
    pctRank1D: 90,
    pctRank3D: 92,
    pctRank5D: 85,
    pctRank10D: 80,
    pctRank20D: 70,
    previous3dReturn: 0.004,
    previous5dReturn: 0.01,
    momentumAcceleration3D: 0.014,
    momentumAcceleration5D: 0.0134,
    rankChange1D: 1,
    rankChange3D: 2,
    rankChange5D: 4,
    ma10Ratio: 0.015,
    ma20Ratio: 0.02,
    volumeRatio5D: 1.2,
    avgAmount20D: 1000,
    realizedVol20D: 0.2,
    referencePrice: 100,
    stopLossPct: 0.05,
    suggestedStopPrice: 95,
    distanceFrom20dHigh: -0.01,
    weightedSlope5D: 0.012,
    weightedSlope10D: 0.01,
    weightedSlope15D: 0.008,
    annualizedSlope5D: 1.5,
    annualizedSlope10D: 1.2,
    annualizedSlope15D: 0.9,
    trendR215D: 0.9,
    trendQuality15D: 0.81,
    signedEfficiencyRatio10D: 0.8,
    trendAcceleration: 0.3,
    rs5D: 0.025,
    rs10D: 0.03,
    rs20D: 0.03,
    relativeStrengthReady: true,
    maxDrawdown20D: -0.05,
    momentumScore: 80.1,
    momentumStrengthScore: 80.1,
    trendQualityScore: 85,
    relativeStrengthScore: 82,
    accelerationScore: 75,
    efficiencyScore: 88,
    compositeScore: 82.5,
    rank: 3,
    entryScore: 88.2,
    absoluteTrendEligible: true,
    liquidityEligible: true,
    action: 'BUY',
    state: 'TRENDING',
    overheated: false,
    candidateRank: 1,
    isCandidate: true,
    scoreComponents: { baseMomentum: 70 },
    diagnostics: {},
    generatedAt: '2026-08-25T10:40:00+00:00',
    ...overrides,
  };
}

function rankingPayload(market: ETFMarket, tradeDate: string, item: ETFMomentumSnapshot) {
  return {
    market,
    tradeDate,
    universeSize: market === 'US' ? 49 : 40,
    dataReadyCount: market === 'US' ? 49 : 40,
    dataCoverage: 1,
    rankableSize: market === 'US' ? 49 : 40,
    rankableCoverage: 1,
    generatedAt: `${tradeDate}T10:40:00Z`,
    warnings: [],
    marketSnapshot: {
      market, tradeDate, regime: 'RISK_ON', positive5dBreadth: 0.8, aboveMa10Breadth: 0.7,
      benchmarkCode: market === 'US' ? 'SPY.US' : '510300.SH',
      benchmarkClose: 100, benchmarkRet5D: 0.02, benchmarkMa10Ratio: 0.03,
      benchmarkWeightedSlope10D: 0.01, benchmarkTrend: 'POSITIVE',
    },
    changes: {
      previousTradeDate: '2026-08-22', newBuys: [], newExits: [], newEmerging: [],
      newCooling: [], regimeChange: null, rankMovers: [],
    },
    items: [item],
  };
}

describe('ETFRotationPage', () => {
  beforeEach(() => {
    apiMocks.dates.mockImplementation(async (market: ETFMarket = 'CN') => (
      market === 'US'
        ? { market: 'US', latest: '2026-08-20', items: ['2026-08-20'] }
        : { market: 'CN', latest: '2026-08-25', items: ['2026-08-25', '2026-08-21'] }
    ));
    apiMocks.ranking.mockImplementation(async (market: ETFMarket = 'CN', tradeDate?: string) => {
      if (market === 'US') {
        const date = tradeDate || '2026-08-20';
        const item = snapshot({
          market: 'US',
          tradeDate: date,
          code: 'SPY.US',
          name: 'SPDR S&P 500 ETF',
          theme: 'SP500',
          riskGroup: 'BROAD_MARKET',
        });
        return rankingPayload('US', date, item);
      }
      const date = tradeDate || '2026-08-25';
      const item = snapshot({
        tradeDate: date,
        code: date === '2026-08-21' ? '159915.SZ' : '588000.SH',
        name: date === '2026-08-21' ? '创业板ETF' : '科创50ETF',
        ret1D: date === '2026-08-21' ? 0.02 : 0.011,
      });
      return rankingPayload('CN', date, item);
    });
    apiMocks.candidates.mockImplementation(async (market: ETFMarket = 'CN', tradeDate?: string) => {
      if (market === 'US') {
        const date = tradeDate || '2026-08-20';
        const candidate = snapshot({
          market: 'US',
          tradeDate: date,
          code: 'SPY.US',
          name: 'SPDR S&P 500 ETF',
          theme: 'SP500',
          riskGroup: 'BROAD_MARKET',
        });
        const exit = snapshot({ market: 'US', tradeDate: date, code: 'QQQ.US', name: 'Invesco QQQ',
          action: 'EXIT', state: 'COOLING', isCandidate: false, candidateRank: null });
        return {
          market: 'US',
          tradeDate: date,
          items: [candidate, exit],
          candidates: [candidate],
          exits: [exit],
        };
      }
      const date = tradeDate || '2026-08-25';
      const candidate = snapshot({
        tradeDate: date,
        code: date === '2026-08-21' ? '159915.SZ' : '588000.SH',
        name: date === '2026-08-21' ? '创业板ETF' : '科创50ETF',
      });
      const exit = snapshot({ tradeDate: date, code: '510050.SH', name: '上证50ETF',
        action: 'EXIT', state: 'COOLING', isCandidate: false, candidateRank: null });
      return {
        market: 'CN',
        tradeDate: date,
        items: [candidate, exit],
        candidates: [candidate],
        exits: [exit],
      };
    });
    apiMocks.detail.mockImplementation(async (code: string, market: ETFMarket = 'CN') => {
      const item = snapshot({ code, market, name: market === 'US' ? 'SPDR S&P 500 ETF' : '科创50ETF' });
      return { market, metadata: item, latest: item, history: [item], marketSnapshot: null };
    });
    apiMocks.preview.mockResolvedValue(null);
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('keeps 5D and 20D in the ranking and full returns in detail', async () => {
    const wrapper = mount(ETFRotationPage, { attachTo: document.body });
    await flushPromises();

    expect(document.body.textContent).toContain('科创50ETF');
    expect(wrapper.findAll('thead th')).toHaveLength(11);
    await wrapper.get('tbody tr').trigger('click');
    await flushPromises();
    expect(document.body.textContent).toContain('+1.10%');
    expect(document.body.textContent).toContain('+2.34%');
    expect(document.body.textContent).toContain('-1.20%');
    expect(document.body.textContent).toContain('+4.00%');
    expect(document.body.textContent).toContain('+1.80%');
    expect(document.body.textContent).toContain('-5.0%');
    expect(document.body.textContent).toContain('¥95.00');
    expect(document.body.textContent).toContain('#3');
    expect(document.body.textContent).toContain('+4');
    expect(apiMocks.ranking).toHaveBeenCalledWith('CN', undefined);
    expect(document.body.querySelector('[aria-label="查看 3D 指标说明与计算公式"]')).not.toBeNull();
    expect(document.body.querySelector('[aria-label="查看 Entry 指标说明与计算公式"]')).not.toBeNull();
  });

  it('documents both explanations and the complete fast-rotation formulas in indicator hints', () => {
    expect(indicatorDescriptions.momentum).toContain('动量强度分');
    expect(indicatorDescriptions.momentum).toContain('0.30×PctRank(Return3)');
    expect(indicatorDescriptions.composite).toContain('当前强势越全面');
    expect(indicatorDescriptions.relativeStrength).toContain('RS_N = ETF Return_N − Benchmark Return_N');
    expect(indicatorDescriptions.acceleration).toContain('Acc3 =');
    expect(indicatorDescriptions.composite).toContain('0.25×Acceleration');
    expect(indicatorDescriptions.entry).toContain('BUY 阈值为 70');
    expect(indicatorDescriptions.breadth).toContain('RankableCount');
    expect(indicatorDescriptions.stop).toContain('RealizedVol20/√252');
  });

  it('loads the latest snapshot on mount and fills the date picker', async () => {
    const wrapper = mount(ETFRotationPage, { attachTo: document.body });
    await flushPromises();

    expect(apiMocks.dates).toHaveBeenCalledWith('CN');
    expect(apiMocks.ranking).toHaveBeenCalledWith('CN', undefined);
    expect(apiMocks.candidates).toHaveBeenCalledWith('CN', '2026-08-25');
    expect(wrapper.get('[data-testid="etf-rotation-trade-date"]').text()).toBe('2026-08-25');
    expect(wrapper.get('[data-testid="etf-rotation-date"]').element).toHaveProperty('value', '2026-08-25');
    expect(wrapper.text()).toContain('科创50ETF');
  });

  it('keeps every control in the snapshot action bar the same height', async () => {
    const wrapper = mount(ETFRotationPage);
    await flushPromises();

    const controls = [
      wrapper.get('[aria-label="市场"]'),
      wrapper.get('[data-testid="etf-rotation-refresh"]'),
      wrapper.get('[data-testid="etf-rotation-run"]'),
    ];
    controls.forEach(control => expect(control.classes()).toContain('h-10'));
  });

  it('separates current candidates from unlimited exits and renders today changes', async () => {
    const current = snapshot({ state: 'EMERGING' });
    const change = {
      current,
      previousState: 'NEUTRAL' as const,
      previousAction: null,
      previousRank: 8,
      rankChange: 5,
      compositeScoreChange: 7.2,
    };
    apiMocks.ranking.mockResolvedValueOnce({
      ...rankingPayload('CN', '2026-08-25', current),
      changes: {
        previousTradeDate: '2026-08-22',
        newBuys: [change],
        newExits: [],
        newEmerging: [change],
        newCooling: [],
        regimeChange: { from: 'NEUTRAL', to: 'RISK_ON' },
        rankMovers: [change],
      },
    });
    const wrapper = mount(ETFRotationPage);
    await flushPromises();

    expect(wrapper.get('[data-testid="rotation-candidate"]').text()).toContain('科创50ETF');
    expect(wrapper.get('[data-testid="rotation-exit"]').text()).toContain('上证50ETF');
    expect(wrapper.get('[data-testid="etf-regime-change"]').text()).toContain('NEUTRAL → RISK_ON');
    expect(wrapper.get('[data-testid="etf-change-new-buy"]').text()).toContain('Composite Δ +7.2');
    expect(wrapper.get('[data-testid="etf-change-new-emerging"]').text()).toContain('NEUTRAL → EMERGING');
    expect(wrapper.get('[data-testid="etf-rank-mover"]').text()).toContain('#8 → #3 (+5)');
  });

  it('reloads ranking and candidates for the selected trade date', async () => {
    const wrapper = mount(ETFRotationPage, { attachTo: document.body });
    await flushPromises();

    await wrapper.get('[data-testid="etf-rotation-date"]').setValue('2026-08-21');
    await flushPromises();

    expect(apiMocks.ranking).toHaveBeenLastCalledWith('CN', '2026-08-21');
    expect(apiMocks.candidates).toHaveBeenLastCalledWith('CN', '2026-08-21');
    expect(wrapper.get('[data-testid="etf-rotation-trade-date"]').text()).toBe('2026-08-21');
    expect(wrapper.text()).toContain('创业板ETF');
    expect(wrapper.text()).not.toContain('科创50ETF');
  });

  it('resets the selected date and reloads US snapshots when switching markets', async () => {
    const wrapper = mount(ETFRotationPage, { attachTo: document.body });
    await flushPromises();
    await wrapper.get('[data-testid="etf-rotation-date"]').setValue('2026-08-21');
    await flushPromises();

    await wrapper.get('[aria-label="市场"]').setValue('US');
    await flushPromises();

    expect(apiMocks.dates).toHaveBeenLastCalledWith('US');
    expect(apiMocks.ranking).toHaveBeenCalledWith('US', undefined);
    expect(apiMocks.ranking).not.toHaveBeenCalledWith('US', '2026-08-21');
    expect(apiMocks.ranking).toHaveBeenLastCalledWith('US', undefined);
    expect(apiMocks.candidates).toHaveBeenLastCalledWith('US', '2026-08-20');
    expect(wrapper.get('[data-testid="etf-rotation-trade-date"]').text()).toBe('2026-08-20');
    expect(wrapper.get('[data-testid="etf-rotation-date"]').element).toHaveProperty('value', '2026-08-20');
    expect(wrapper.text()).toContain('SPDR S&P 500 ETF');
    expect(wrapper.text()).not.toContain('创业板ETF');
    expect(wrapper.text()).toContain('$95.00');
  });

  it('opens a centered viewport-bounded detail modal with factor and raw metrics', async () => {
    mount(ETFRotationPage, { attachTo: document.body });
    await flushPromises();
    const candidate = document.body.querySelector('[data-testid="rotation-candidate"]') as HTMLElement;
    candidate.click();
    await flushPromises();

    const modal = document.body.querySelector('[data-testid="etf-detail-modal"]');
    expect(modal).not.toBeNull();
    expect(modal?.className).toContain('max-h-[calc(100dvh-2rem)]');
    expect(modal?.className).toContain('sm:max-w-[calc(100%-2rem)]');
    expect(modal?.className).toContain('lg:max-w-6xl');
    expect(document.body.querySelector('[data-testid="etf-factor-grid"]')?.className)
      .toContain('grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]');
    expect(document.body.querySelector('[data-testid="etf-raw-metrics-grid"]')?.className)
      .toContain('grid-cols-[repeat(auto-fit,minmax(11rem,1fr))]');
    expect(document.body.textContent).toContain('Raw Metrics');
    expect(document.body.textContent).toContain('Weighted Slope 15D');
    expect(document.body.textContent).toContain('RS10');
    expect(document.body.textContent).toContain('Signed ER10');
    expect(apiMocks.detail).toHaveBeenCalledWith('588000.SH', 'CN');
  });

  it('renders nullable actions and snapshot warnings without treating them as signals', async () => {
    const item = snapshot({ action: null, isCandidate: false, candidateRank: null, state: 'WEAK' });
    apiMocks.ranking.mockResolvedValueOnce({
      ...rankingPayload('CN', '2026-08-25', item),
      warnings: ['benchmark 510300.SH missing; latest valid snapshot retained'],
    });
    apiMocks.candidates.mockResolvedValueOnce({ market: 'CN', tradeDate: '2026-08-25', items: [] });

    const wrapper = mount(ETFRotationPage);
    await flushPromises();

    expect(wrapper.get('[role="alert"]').text()).toContain('benchmark 510300.SH missing');
    expect(wrapper.text()).not.toContain('WATCH');
  });

  it('defaults to preview when preview trade date is newer and does not call candidates', async () => {
    const official = snapshot({ tradeDate: '2026-08-25', name: '半导体ETF', code: '512480.SH', compositeScore: 74.1, rank: 6, action: 'HOLD', isCandidate: false });
    const previewItem = snapshot({
      tradeDate: '2026-09-10', name: '半导体ETF', code: '512480.SH',
      compositeScore: 81.3, rank: 2, candidateRank: 2, action: 'BUY', isCandidate: true, state: 'EMERGING',
    });
    apiMocks.ranking.mockResolvedValue(rankingPayload('CN', '2026-08-25', official));
    apiMocks.preview.mockResolvedValue({
      status: 'completed',
      market: 'CN',
      tradeDate: '2026-09-10',
      previewTime: '2026-09-10T06:35:06Z',
      dataAsOf: '2026-09-10T06:34:57Z',
      provider: 'easyquotation_tencent',
      universeSize: 40,
      dataCoverage: 1,
      warnings: [],
      marketSnapshot: rankingPayload('CN', '2026-09-10', previewItem).marketSnapshot,
      items: [previewItem],
    });
    const wrapper = mount(ETFRotationPage);
    await flushPromises();

    expect(apiMocks.preview).toHaveBeenCalledWith('CN');
    expect(apiMocks.candidates).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="research-data-mode-badge"]').text()).toContain('盘中预演');
    expect(wrapper.get('[data-testid="research-data-as-of"]').text()).toContain(':');
    expect(wrapper.get('[data-testid="research-preview-time"]').text()).toContain(':');
    expect(wrapper.get('[data-testid="research-provider"]').text()).toBe('Tencent');
    expect(wrapper.get('[data-testid="rotation-candidate"]').text()).toContain('半导体ETF');
    expect(wrapper.get('[data-testid="rotation-candidate-vs-official"]').text()).toContain('vs 正式');
    expect(wrapper.get('[data-testid="etf-preview-change-new-buy"]').text()).toContain('半导体ETF');
    expect(wrapper.find('[data-testid="etf-rotation-date"]').exists()).toBe(false);
  });

  it('defaults to official when the same-day official snapshot is newer', async () => {
    const item = snapshot({ tradeDate: '2026-08-25' });
    apiMocks.ranking.mockResolvedValue({
      ...rankingPayload('CN', '2026-08-25', item),
      generatedAt: '2026-08-25T10:40:00Z',
    });
    apiMocks.preview.mockResolvedValue({
      status: 'completed',
      market: 'CN',
      tradeDate: '2026-08-25',
      previewTime: '2026-08-25T06:35:00Z',
      dataAsOf: '2026-08-25T06:34:00Z',
      provider: 'easyquotation_tencent',
      universeSize: 40,
      dataCoverage: 1,
      warnings: [],
      marketSnapshot: rankingPayload('CN', '2026-08-25', item).marketSnapshot,
      items: [item],
    });
    const wrapper = mount(ETFRotationPage);
    await flushPromises();

    expect(wrapper.get('[data-testid="research-data-mode-badge"]').text()).toContain('正式收盘');
    expect(apiMocks.candidates).toHaveBeenCalledWith('CN', '2026-08-25');
    expect(wrapper.get('[data-testid="etf-rotation-date"]').element).toHaveProperty('value', '2026-08-25');
    expect(wrapper.find('[data-testid="etf-preview-changes"]').exists()).toBe(false);
  });

  it('keeps a manual preview/official choice after refresh', async () => {
    const official = snapshot({ tradeDate: '2026-08-25' });
    const previewItem = snapshot({ tradeDate: '2026-09-10', name: '半导体ETF', code: '512480.SH', isCandidate: true, action: 'BUY' });
    apiMocks.ranking.mockResolvedValue(rankingPayload('CN', '2026-08-25', official));
    apiMocks.preview.mockResolvedValue({
      status: 'completed', market: 'CN', tradeDate: '2026-09-10',
      previewTime: '2026-09-10T06:35:06Z', dataAsOf: '2026-09-10T06:34:57Z',
      provider: 'easyquotation_tencent', universeSize: 40, dataCoverage: 1, warnings: [],
      marketSnapshot: rankingPayload('CN', '2026-09-10', previewItem).marketSnapshot,
      items: [previewItem],
    });
    const wrapper = mount(ETFRotationPage);
    await flushPromises();
    expect(wrapper.get('[data-testid="research-data-mode-badge"]').text()).toContain('盘中预演');
    await wrapper.get('[data-testid="research-mode-official"]').trigger('click');
    await flushPromises();
    expect(wrapper.get('[data-testid="research-data-mode-badge"]').text()).toContain('正式收盘');
    expect(apiMocks.candidates).toHaveBeenCalled();
    await wrapper.get('[data-testid="etf-rotation-refresh"]').trigger('click');
    await flushPromises();
    expect(wrapper.get('[data-testid="research-data-mode-badge"]').text()).toContain('正式收盘');
  });

  it('keeps official working when preview is missing', async () => {
    const wrapper = mount(ETFRotationPage);
    await flushPromises();
    expect(wrapper.get('[data-testid="research-mode-preview"]').attributes('disabled')).toBeDefined();
    expect(wrapper.get('[data-testid="research-data-mode-badge"]').text()).toContain('正式收盘');
    expect(wrapper.get('[data-testid="rotation-candidate"]').text()).toContain('科创50ETF');
  });

  it('does not treat incomplete preview items as trading signals', async () => {
    const item = snapshot({ tradeDate: '2026-09-10', name: '半导体ETF', isCandidate: true, action: 'BUY' });
    apiMocks.preview.mockResolvedValue({
      status: 'failed',
      market: 'CN',
      tradeDate: '2026-09-10',
      previewTime: '2026-09-10T06:35:06Z',
      dataAsOf: null,
      provider: 'easyquotation_tencent',
      universeSize: 40,
      dataCoverage: 0,
      warnings: ['easyquotation tencent real failed'],
      marketSnapshot: null,
      items: [item],
    });
    const wrapper = mount(ETFRotationPage);
    await flushPromises();
    await wrapper.get('[data-testid="research-mode-preview"]').trigger('click');
    await flushPromises();
    expect(wrapper.get('[data-testid="research-data-mode-badge"]').text()).toContain('盘中预演不可用');
    expect(wrapper.find('[data-testid="rotation-candidate"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="research-preview-reason"]').text()).toContain('easyquotation tencent real failed');
  });
});
