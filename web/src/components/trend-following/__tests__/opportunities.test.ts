import { describe, it, expect } from 'vitest';
import { filterOpportunities, type OpportunityItem, type OpportunityBranch } from '../opportunities';
import { opportunityOverlays } from '@/components/market-data/opportunityOverlay';
const branch = { kind: 'ma10', structureId: 'a', status: 'CONFIRMED', qualityScore: 60,
  trigger: 100, invalidation: 95, dataAsOf: '2026-11-13', startDate: '2026-11-10',
  anchorDate: '2026-11-13', anchorClose: 102, points: [] } as unknown as OpportunityBranch;
const item = (code: string, score: number | null): OpportunityItem => ({ code, name: code, primary: { ...branch, qualityScore: score },
  display: null, branches: [branch], historyStatus: 'complete', dataAsOf: branch.dataAsOf });
describe('opportunity research view', () => {
  it('filters and globally sorts before pagination with nulls last in both directions', () => {
    const rows = Array.from({ length: 25 }, (_, i) => item(`A${i}`, i === 0 ? null : i));
    expect(filterOpportunities(rows, 'CONFIRMED', 'ma10', '', 'qualityScore', 'desc').slice(0, 10)[0]?.code).toBe('A24');
    expect(filterOpportunities(rows, '', '', '', 'qualityScore', 'asc').at(-1)?.code).toBe('A0');
    expect(filterOpportunities(rows, 'EXTENDED', '', '', null, 'asc')).toHaveLength(0);
    expect(filterOpportunities(rows, '', '', 'A24', null, 'asc')).toHaveLength(1);
  });
  it('draws saved evidence with the chart adjustment factor and independent overlay group', () => {
    const result = opportunityOverlays(branch, [{ tradeDate: branch.anchorDate, close: 51 }], false);
    expect(result[0]?.points?.[0]?.value).toBe(50);
    expect(result[1]?.points?.[0]?.value).toBe(47.5);
    expect(result.every(r => r.groupId === 'backend-opportunity')).toBe(true);
    expect(opportunityOverlays(branch, [], false)).toEqual([]);
  });
});
