import { registerOverlay, type OverlayCreate } from 'klinecharts';
import type { OpportunityBranch } from '@/components/trend-following/opportunities';
let registered = false;
export function opportunityOverlays(branch: OpportunityBranch | undefined, bars: readonly { tradeDate: string; close: number }[], dark: boolean): OverlayCreate[] {
  if (!branch) return [];
  const anchor = bars.find(b => b.tradeDate === branch.anchorDate);
  // Historical price adjustment must be mapped to the current chart basis, never silently guessed.
  if (!anchor || !branch.anchorClose) return [];
  if (!registered) {
    registerOverlay<{ color: string }>({ name: 'opportunityEvidence', totalStep: 1, needDefaultPointFigure: false,
      needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates, overlay }) => coordinates.slice(1).map((point, i) => ({
        type: 'line', attrs: { coordinates: [coordinates[i]!, point] },
        styles: { color: overlay.extendData.color, size: 1.5, style: 'dashed' }, ignoreEvent: true,
      })),
    });
    registered = true;
  }
  const scale = anchor.close / branch.anchorClose;
  const point = (date: string, value: number) => ({ timestamp: Date.parse(`${date}T00:00:00Z`), value: value * scale });
  return [
    ...(['trigger', 'invalidation'] as const).map(key => ({ name: 'opportunityEvidence', groupId: 'backend-opportunity',
      id: `backend-opportunity-${key}`, lock: true,
      points: [point(branch.startDate, branch[key]), point(branch.dataAsOf, branch[key])],
      extendData: { color: key === 'trigger' ? dark ? '#e5e5e5' : '#404040' : '#a3a3a3' },
    })),
    ...(branch.points.length > 1 ? [{ name: 'opportunityEvidence', groupId: 'backend-opportunity',
      id: 'backend-opportunity-waves', lock: true, points: branch.points.map(p => point(p.date, p.price)),
      extendData: { color: dark ? '#f9a8d4' : '#be185d' } }] : []),
  ];
}
