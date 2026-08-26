import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ETFMarket, ETFMomentumSnapshot } from '@/types/etfRotation';
import ETFRotationPage from '../ETFRotationPage.vue';

const apiMocks = vi.hoisted(() => ({
  ranking: vi.fn(),
  candidates: vi.fn(),
  dates: vi.fn(),
  detail: vi.fn(),
  run: vi.fn(),
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
    assetRegion: 'CN',
    crossBorder: false,
    ret1D: 0.011,
    ret5D: 0.0234,
    ret10D: -0.012,
    ret20D: 0.04,
    ret30D: 0.05,
    ret60D: 0.0611,
    rank1D: 4,
    rank5D: 3,
    rank10D: 5,
    rank20D: 6,
    rank30D: 7,
    rank60D: 8,
    pctRank1D: 90,
    pctRank5D: 85,
    pctRank10D: 80,
    pctRank20D: 70,
    pctRank30D: 60,
    pctRank60D: 50,
    previous5dReturn: 0.01,
    momentumAcceleration: 0.0134,
    rankChange1D: 1,
    rankChange3D: 2,
    rankChange5D: 4,
    ma20Ratio: 0.02,
    ma60Ratio: 0.03,
    volumeRatio5D: 1.2,
    avgAmount20D: 1000,
    realizedVol20D: 0.2,
    referencePrice: 100,
    stopLossPct: 0.05,
    suggestedStopPrice: 95,
    distanceFrom20dHigh: -0.01,
    momentumScore: 80.1,
    entryScore: 88.2,
    state: 'TRENDING',
    overheated: false,
    candidateRank: 1,
    isCandidate: true,
    scoreComponents: { baseMomentum: 70 },
    generatedAt: '2026-08-25T10:40:00+00:00',
    ...overrides,
  };
}

function rankingPayload(market: ETFMarket, tradeDate: string, item: ETFMomentumSnapshot) {
  return {
    market,
    tradeDate,
    universeSize: market === 'US' ? 49 : 42,
    dataReadyCount: market === 'US' ? 49 : 42,
    dataCoverage: 1,
    rankableSize: market === 'US' ? 49 : 42,
    rankableCoverage: 1,
    generatedAt: `${tradeDate}T10:40:00Z`,
    warnings: [],
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
        return {
          market: 'US',
          tradeDate: date,
          items: [snapshot({
            market: 'US',
            tradeDate: date,
            code: 'SPY.US',
            name: 'SPDR S&P 500 ETF',
            theme: 'SP500',
            riskGroup: 'BROAD_MARKET',
          })],
        };
      }
      const date = tradeDate || '2026-08-25';
      return {
        market: 'CN',
        tradeDate: date,
        items: [snapshot({
          tradeDate: date,
          code: date === '2026-08-21' ? '159915.SZ' : '588000.SH',
          name: date === '2026-08-21' ? '创业板ETF' : '科创50ETF',
        })],
      };
    });
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('renders 1D-60D returns instead of placeholders when snapshot values exist', async () => {
    const wrapper = mount(ETFRotationPage);
    await flushPromises();

    expect(wrapper.text()).toContain('科创50ETF');
    expect(wrapper.text()).toContain('+1.10%');
    expect(wrapper.text()).toContain('+2.34%');
    expect(wrapper.text()).toContain('-1.20%');
    expect(wrapper.text()).toContain('+4.00%');
    expect(wrapper.text()).toContain('+5.00%');
    expect(wrapper.text()).toContain('+6.11%');
    expect(wrapper.text()).toContain('-5.0%');
    expect(wrapper.text()).toContain('¥95.00');
    expect(wrapper.text()).toContain('#3');
    expect(wrapper.text()).toContain('+4');
    expect(apiMocks.ranking).toHaveBeenCalledWith('CN', undefined);
  });

  it('renders a CN cross-border ETF with the shared metadata columns', async () => {
    const item = snapshot({
      code: '159941.SZ',
      name: '广发纳指100ETF',
      category: 'OVERSEAS_INDEX',
      theme: 'NASDAQ100',
      riskGroup: 'US_GROWTH',
      assetRegion: 'US',
      crossBorder: true,
    });
    apiMocks.ranking.mockResolvedValue(rankingPayload('CN', '2026-08-25', item));
    apiMocks.candidates.mockResolvedValue({ market: 'CN', tradeDate: '2026-08-25', items: [item] });

    const wrapper = mount(ETFRotationPage);
    await flushPromises();

    expect(wrapper.text()).toContain('广发纳指100ETF');
    expect(wrapper.text()).toContain('OVERSEAS_INDEX');
    expect(wrapper.text()).toContain('NASDAQ100');
    expect(wrapper.text()).toContain('US_GROWTH');
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
});
