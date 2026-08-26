import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ETFRotationPage from '../ETFRotationPage.vue';
import type { ETFMomentumSnapshot } from '@/types/etfRotation';
import { etfRotationApi } from '@/api/etfRotation';

vi.mock('@/api/etfRotation', () => ({
  etfRotationApi: {
    ranking: vi.fn(),
    candidates: vi.fn(),
    detail: vi.fn(),
    run: vi.fn(),
  },
}));

const snapshot: ETFMomentumSnapshot = {
  id: 1,
  tradeDate: '2026-08-25',
  code: '588000.SH',
  name: '科创50ETF',
  category: 'BROAD_INDEX',
  theme: 'STAR50',
  riskGroup: 'BROAD_GROWTH',
  enabled: true,
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
  distanceFrom20dHigh: -0.01,
  momentumScore: 80.1,
  entryScore: 88.2,
  state: 'TRENDING',
  overheated: false,
  candidateRank: 1,
  isCandidate: true,
  scoreComponents: { baseMomentum: 70 },
  generatedAt: '2026-08-25T10:40:00+00:00',
};

describe('ETFRotationPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(etfRotationApi.ranking).mockResolvedValue({
      tradeDate: '2026-08-25',
      universeSize: 40,
      dataReadyCount: 40,
      dataCoverage: 1,
      rankableSize: 40,
      rankableCoverage: 1,
      generatedAt: snapshot.generatedAt,
      warnings: [],
      items: [snapshot],
    });
    vi.mocked(etfRotationApi.candidates).mockResolvedValue({
      tradeDate: '2026-08-25',
      items: [snapshot],
    });
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
    expect(wrapper.text()).toContain('#3');
    expect(wrapper.text()).toContain('+4');
  });
});
