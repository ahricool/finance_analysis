import { registerOverlay, type OverlayCreate } from 'klinecharts';
import type { DailyBar } from '@/api/marketData';
import type { DailyPatternEvent } from '@/utils/dailyPatterns';
import { MARKET_HEX } from '@/utils/marketColors';

let registered = false;
export function dailyPatternOverlays(
  events: DailyPatternEvent[], bars: readonly DailyBar[], dark: boolean,
  onSelect: (event: DailyPatternEvent) => void,
  onHover?: (event: DailyPatternEvent | null) => void,
): OverlayCreate[] {
  if (!registered) {
    registerOverlay<DailyPatternEvent & { dark: boolean }>({
      name: 'dailyPattern', totalStep: 1,
      needDefaultPointFigure: false, needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates, overlay, bounding }) => {
        const point = coordinates[0];
        if (!point) return [];
        const event = overlay.extendData;
        const bullish = event.direction === 'bullish';
        const neutral = event.direction === 'neutral';
        const palette = event.dark ? MARKET_HEX.dark : MARKET_HEX.light;
        return [{ type: 'text', attrs: { x: point.x, y: Math.max(10, Math.min(bounding.height - 30, point.y + (bullish ? 14 : -14))),
          text: neutral ? '◇' : bullish ? '▴' : '▾', align: 'center', baseline: 'middle' },
        styles: { color: neutral ? '#888888' : bullish ? palette.up : palette.down,
          size: 12, weight: event.confirmed ? 'bold' : 'normal', backgroundColor: 'transparent',
          borderColor: 'transparent', borderSize: 0, paddingLeft: 3, paddingRight: 3, paddingTop: 3, paddingBottom: 3 } }];
      },
    });
    registered = true;
  }
  const byDate = new Map(bars.map(bar => [bar.tradeDate, bar]));
  return events.flatMap(event => {
    const bar = byDate.get(event.date);
    if (!bar) return [];
    return [{ name: 'dailyPattern', id: `daily-pattern-${event.date}`, groupId: 'daily-patterns', lock: true,
      points: [{ timestamp: event.timestamp, value: event.direction === 'bullish' ? bar.low : bar.high }],
      extendData: { ...event, dark }, onClick: () => { onSelect(event); },
      onMouseEnter: () => { onHover?.(event); }, onMouseLeave: () => { onHover?.(null); } }];
  });
}
