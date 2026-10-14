import { registerOverlay, type OverlayCreate, type OverlayFigure } from 'klinecharts';
import type { DailyStructureEvent } from '@/utils/dailyStructures';
import { MARKET_HEX } from '@/utils/marketColors';

let registered = false;
export function dailyStructureOverlays(
  events: readonly DailyStructureEvent[], dark: boolean, selectedId: string | undefined,
  onSelect: (event: DailyStructureEvent) => void, onHover: (event: DailyStructureEvent | null) => void,
): OverlayCreate[] {
  if (!registered) {
    registerOverlay<{ event: DailyStructureEvent; dark: boolean; selected: boolean }>({
      name: 'dailyStructure', totalStep: 1,
      needDefaultPointFigure: false, needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates, overlay, bounding }) => {
        const point = coordinates[0];
        if (!point) return [];
        const { event, dark, selected } = overlay.extendData;
        const palette = dark ? MARKET_HEX.dark : MARKET_HEX.light;
        const color = event.status === 'invalidated' || event.direction === 'neutral' ? '#888888' :
          event.direction === 'bullish' ? palette.up : palette.down;
        // A separate small marker lane, outside candle bodies. No names or evidence on canvas.
        const figures: OverlayFigure[] = [{ type: 'text', attrs: { x: point.x, y: bounding.height - 12,
          text: event.status === 'invalidated' ? '×' : '◆', align: 'center', baseline: 'middle' },
          styles: { color, size: 10, weight: selected ? 'bold' : 'normal', backgroundColor: 'transparent',
            borderColor: 'transparent', borderSize: 0, paddingLeft: 3, paddingRight: 3, paddingTop: 3, paddingBottom: 3 } }];
        if (selected) for (let i = 1; i + 1 < coordinates.length; i += 2) {
          const a = coordinates[i]!; const b = coordinates[i + 1]!;
          figures.push({ type: 'line', attrs: { coordinates: [a, b] },
            styles: { color, size: 1, style: 'dashed' }, ignoreEvent: true });
        }
        return figures;
      },
    });
    registered = true;
  }
  // One compact marker per date; all events remain available in the summary/history picker.
  const byDate = new Map<string, DailyStructureEvent>();
  for (const event of events) {
    const previous = byDate.get(event.date);
    if (!previous || event.id === selectedId || (previous.id !== selectedId && event.quality > previous.quality)) byDate.set(event.date, event);
  }
  return [...byDate.values()].map(event => {
    const selected = selectedId === event.id;
    return { name: 'dailyStructure', id: `daily-structure-${event.date}`, groupId: 'daily-structures', lock: true,
      points: [{ timestamp: event.timestamp, value: event.lines[0]!.endValue },
        ...(selected ? event.lines.flatMap(line => [
          { timestamp: Date.parse(`${line.startDate}T00:00:00Z`), value: line.startValue },
          { timestamp: Date.parse(`${line.endDate}T00:00:00Z`), value: line.endValue },
        ]) : [])], extendData: { event, dark, selected },
      onClick: () => { onSelect(event); }, onMouseEnter: () => { onHover(event); }, onMouseLeave: () => { onHover(null); },
    };
  });
}
