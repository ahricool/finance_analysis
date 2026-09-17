import { describe, expect, it } from 'vitest';
import type { IndustrySnapshot } from '@/api/industryStrength';
import {
  breadthMissingReason,
  computeSummary,
  filterRankingRows,
  formatPercent,
  formatPoints,
  formatPulse,
  formatRankDelta,
  heatmapNormalizedRank,
  methodologyLines,
  rankingColumns,
  selectedDateLeaders,
  stateCounts,
  coverageInsufficient,
} from '../display';

function row(overrides: Partial<IndustrySnapshot> = {}): IndustrySnapshot {
  return {
    tradeDate: '2026-09-16', industryCode: '881101.TI', industryName: '行业甲', state: 'STRONG', close: 100,
    strengthRank: 1, strengthScore: 90, ret1D: 0.01, ret5D: 0.03, ret10D: 0.04, ret20D: 0.05,
    rs5D: 0.01, rs10D: 0.02, rs20D: 0.03, rankChange1D: 2, rankChange3D: 5, rankChange5D: null,
    previous5DReturn: 0.01, momentumAcceleration5D: 0.02, accelerationPercentile: 80, turnoverRatio5D: 1.2,
    upRatio: 0.7, aboveMa5Ratio: 0.8, aboveMa20Ratio: 0.9, equalWeightReturn: 0.01,
    constituentCount: 10, dailyValidCount: 10, ma5ValidCount: 10, aboveMa5Count: 8, ma20ValidCount: 10, aboveMa20Count: 9,
    upCount: 7, downCount: 2, flatCount: 1,
    dataTimestamp: '2026-09-16T07:00:00Z', membersObservedAt: '2026-09-16T11:00:00Z',
    createdAt: '2026-09-16T11:05:00Z', updatedAt: '2026-09-16T11:05:00Z',
    quality: { dailyBreadthCoverage: 1, ma5Coverage: 1, ma20Coverage: 1, catalogCount: 2, rankedCount: 2, coverage: 1, excluded: {} },
    ...overrides,
  };
}

describe('industry strength display', () => {
  it('formats percent, percentage points, ranks and pulse without filling missing as zero', () => {
    expect(formatPercent(0.7)).toBe('70.0%');
    expect(formatPercent(0)).toBe('0.0%');
    expect(formatPercent(null)).toBe('—');
    expect(formatPercent(0.7, { unit: false })).toBe('70.0');
    expect(formatPoints(0.02)).toBe('2.00 个百分点');
    expect(formatPoints(0)).toBe('0.00 个百分点');
    expect(formatPoints(null)).toBe('—');
    expect(formatPoints(-0.015, { unit: false })).toBe('-1.50');
    expect(formatRankDelta(8)).toBe('↑8 名');
    expect(formatRankDelta(-3)).toBe('↓3 名');
    expect(formatRankDelta(0)).toBe('持平');
    expect(formatRankDelta(null)).toBe('—');
    expect(formatPulse(1.2)).toBe('1.20×');
    expect(formatPulse(null)).toBe('—');
  });

  it('computes summary from the ranked valid industries and does not treat empty as 0%', () => {
    const rows = [
      row({ strengthRank: 2, industryName: '乙', industryCode: 'B', momentumAcceleration5D: -0.03, ret1D: -0.01 }),
      row({ strengthRank: 1, industryName: '甲', industryCode: 'A', momentumAcceleration5D: 0.04, ret1D: 0.02 }),
      row({ strengthRank: 3, industryName: '丙', industryCode: 'C', momentumAcceleration5D: 0.01, ret1D: 0 }),
    ];
    const summary = computeSummary(rows);
    expect(summary.strongest?.industryName).toBe('甲');
    expect(summary.accelerating?.industryName).toBe('甲');
    expect(summary.decelerating?.industryName).toBe('乙');
    expect(summary.validCount).toBe(3);
    expect(summary.advancingCount).toBe(1);
    expect(summary.advancingLabel).toBe('33.3%（1 / 3）');
    expect(computeSummary([]).advancingLabel).toBe('暂无有效行业');
  });

  it('keeps original ranks when filtering and counts states from the full set', () => {
    const rows = [
      row({ strengthRank: 1, industryName: '半导体', industryCode: '881101.TI', state: 'STRONG' }),
      row({ strengthRank: 8, industryName: '银行', industryCode: '881102.TI', state: 'WEAK' }),
    ];
    expect(stateCounts(rows).STRONG).toBe(1);
    expect(filterRankingRows(rows, '银行', 'ALL')[0]).toMatchObject({ strengthRank: 8, industryName: '银行' });
    expect(filterRankingRows(rows, '', 'WEAK')).toHaveLength(1);
  });

  it('keeps selected-day Top20 sample order and normalized ranks', () => {
    const rows = Array.from({ length: 25 }, (_, index) => row({
      industryCode: `${index}.TI`,
      industryName: `行业${index}`,
      strengthRank: index + 1,
    }));
    const leaders = selectedDateLeaders(rows);
    expect(leaders).toHaveLength(20);
    expect(leaders[0]?.strengthRank).toBe(1);
    expect(leaders.at(-1)?.strengthRank).toBe(20);
    expect(heatmapNormalizedRank(1, 21)).toBe(100);
    expect(heatmapNormalizedRank(21, 21)).toBe(0);
  });

  it('does not treat 96% partial coverage as 覆盖不足, but flags coverage below 0.95', () => {
    expect(coverageInsufficient(row({
      quality: {
        ...row().quality,
        dailyBreadthCoverage: 0.96,
        ma5Coverage: 0.96,
        ma20Coverage: 0.96,
        breadthStatus: 'partial',
      },
    }))).toBe(false);
    expect(coverageInsufficient(row({
      quality: { ...row().quality, dailyBreadthCoverage: 0.94, ma5Coverage: 1, ma20Coverage: 1, breadthStatus: 'partial' },
    }))).toBe(true);
    expect(coverageInsufficient(row({
      quality: { ...row().quality, dailyBreadthCoverage: 0.94, ma5Coverage: 1, ma20Coverage: 1 },
    }))).toBe(true);
  });

  it('does not treat historical backfill with zero coverage as 覆盖不足', () => {
    const historical = row({
      upRatio: null,
      aboveMa5Ratio: null,
      aboveMa20Ratio: null,
      quality: {
        ...row().quality,
        dailyBreadthCoverage: 0,
        ma5Coverage: 0,
        ma20Coverage: 0,
        breadthStatus: 'unavailable_historical_members',
      },
    });
    expect(coverageInsufficient(historical)).toBe(false);
    expect(breadthMissingReason(historical, 'up')).toBe('缺少当日成分记录，历史广度不可用');
    expect(breadthMissingReason(historical, 'ma5')).toBe('缺少当日成分记录，历史广度不可用');
    expect(breadthMissingReason(historical, 'ma20')).toBe('缺少当日成分记录，历史广度不可用');
  });

  it('describes ranking within the ranked valid set instead of a complete catalog cross-section', () => {
    expect(methodologyLines.join('\n')).not.toContain('完整截面');
    expect(methodologyLines.join('\n')).toContain('分位和排名均基于当日实际参与排名的有效行业截面');
    expect(rankingColumns.find((column) => column.key === 'strengthRank')?.hint).toContain('当日有效行业截面');
    expect(rankingColumns.find((column) => column.key === 'strengthRank')?.hint).not.toContain('完整截面');
  });
});
