import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ETFMomentumSnapshot } from '@/types/etfRotation';
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
    tradeDate: '2026-08-25',
    code: '588000.SH',
    name: '科创50ETF',
    category: 'BROAD_INDEX',
    theme: 'STAR50',
    riskGroup: 'BROAD_GROWTH',
    enabled: true,
    ret1d: 0.01,
    ret5d: 0.05,
    ret10d: 0.08,
    ret20d: 0.1,
    ret30d: 0.12,
    ret60d: 0.2,
    rank1d: 2,
    rank5d: 3,
    rank10d: 4,
    rank20d: 5,
    rank30d: 6,
    rank60d: 7,
    pctRank1d: 90,
    pctRank5d: 88,
    pctRank10d: 80,
    pctRank20d: 70,
    pctRank30d: 60,
    pctRank60d: 50,
    previous5dReturn: 0.02,
    momentumAcceleration: 0.03,
    rankChange1d: 1,
    rankChange3d: 2,
    rankChange5d: 4,
    ma20Ratio: 1.01,
    ma60Ratio: 1.02,
    volumeRatio5d: 1.2,
    avgAmount20d: 1e8,
    realizedVol20d: 0.2,
    distanceFrom20dHigh: -0.01,
    momentumScore: 80,
    entryScore: 88,
    state: 'STRONG',
    overheated: false,
    candidateRank: 1,
    isCandidate: true,
    scoreComponents: { momentum: 32 },
    generatedAt: '2026-08-25T10:40:00Z',
    ...overrides,
  };
}

function rankingPayload(tradeDate: string, item: ETFMomentumSnapshot) {
  return {
    tradeDate,
    universeSize: 40,
    dataReadyCount: 40,
    dataCoverage: 1,
    rankableSize: 40,
    rankableCoverage: 1,
    generatedAt: `${tradeDate}T10:40:00Z`,
    warnings: [],
    items: [item],
  };
}

describe('ETFRotationPage', () => {
  beforeEach(() => {
    apiMocks.dates.mockResolvedValue({ latest: '2026-08-25', items: ['2026-08-25', '2026-08-21'] });
    apiMocks.ranking.mockImplementation(async (tradeDate?: string) => {
      const date = tradeDate || '2026-08-25';
      const item = snapshot({
        tradeDate: date,
        code: date === '2026-08-21' ? '159915.SZ' : '588000.SH',
        name: date === '2026-08-21' ? '创业板ETF' : '科创50ETF',
        entryScore: date === '2026-08-21' ? 70 : 88,
      });
      return rankingPayload(date, item);
    });
    apiMocks.candidates.mockImplementation(async (tradeDate?: string) => {
      const date = tradeDate || '2026-08-25';
      return {
        tradeDate: date,
        items: [
          snapshot({
            tradeDate: date,
            code: date === '2026-08-21' ? '159915.SZ' : '588000.SH',
            name: date === '2026-08-21' ? '创业板ETF' : '科创50ETF',
          }),
        ],
      };
    });
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('loads the latest snapshot on mount and fills the date picker', async () => {
    const wrapper = mount(ETFRotationPage, { attachTo: document.body });
    await flushPromises();

    expect(apiMocks.dates).toHaveBeenCalledTimes(1);
    expect(apiMocks.ranking).toHaveBeenCalledWith(undefined);
    expect(apiMocks.candidates).toHaveBeenCalledWith('2026-08-25');
    expect(wrapper.get('[data-testid="etf-rotation-trade-date"]').text()).toBe('2026-08-25');
    expect(wrapper.get('[data-testid="etf-rotation-date"]').element).toHaveProperty('value', '2026-08-25');
    expect(wrapper.text()).toContain('科创50ETF');
  });

  it('reloads ranking and candidates for the selected trade date', async () => {
    const wrapper = mount(ETFRotationPage, { attachTo: document.body });
    await flushPromises();

    await wrapper.get('[data-testid="etf-rotation-date"]').setValue('2026-08-21');
    await flushPromises();

    expect(apiMocks.ranking).toHaveBeenLastCalledWith('2026-08-21');
    expect(apiMocks.candidates).toHaveBeenLastCalledWith('2026-08-21');
    expect(wrapper.get('[data-testid="etf-rotation-trade-date"]').text()).toBe('2026-08-21');
    expect(wrapper.text()).toContain('创业板ETF');
    expect(wrapper.text()).not.toContain('科创50ETF');
  });
});
