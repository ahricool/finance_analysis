import { registerOverlay, type OverlayCreate } from 'klinecharts';
import type { IntradayBar, PatternEvent } from '@/api/intradayMarket';
import type { PatternDirection } from '@/api/realtimeMarket';
import { MARKET_HEX } from '@/utils/marketColors';

function directionOf(direction: PatternDirection) {
  switch (direction) {
    case 'bullish_continuation':
    case 'bullish_breakout':
    case 'bearish_to_bullish': return 'bullish';
    case 'bearish_continuation':
    case 'bearish_breakout':
    case 'bullish_to_bearish': return 'bearish';
    case 'neutral_wait': return 'neutral';
  }
}

interface MarkerData { event: PatternEvent; dark: boolean }
let registered = false;

export function intradayPatternOverlays(
  events: readonly PatternEvent[], bars: readonly IntradayBar[], dark: boolean,
  onSelect: (events: PatternEvent[]) => void,
): OverlayCreate[] {
  if (!registered) {
    registerOverlay<MarkerData>({
      name: 'intradayPattern', totalStep: 1,
      needDefaultPointFigure: false, needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates, overlay, bounding }) => {
        const point = coordinates[0];
        if (!point) return [];
        const { event, dark } = overlay.extendData;
        const direction = directionOf(event.direction);
        const palette = dark ? MARKET_HEX.dark : MARKET_HEX.light;
        return [{ type: 'text', attrs: {
          x: point.x, y: Math.max(10, Math.min(bounding.height - 30, point.y + (direction === 'bullish' ? 14 : -14))),
          text: direction === 'neutral' ? '◇' : direction === 'bullish' ? '▴' : '▾', align: 'center', baseline: 'middle',
        }, styles: {
          color: direction === 'neutral' ? '#888888' : direction === 'bullish' ? palette.up : palette.down,
          size: 12, weight: event.stage === 'confirmed' ? 'bold' : 'normal', backgroundColor: 'transparent',
          borderColor: 'transparent', borderSize: 0, paddingLeft: 3, paddingRight: 3, paddingTop: 3, paddingBottom: 3,
        } }];
      },
    });
    registered = true;
  }
  const grouped = new Map<number, { bar: IntradayBar; events: PatternEvent[] }>();
  const newestBars = [...bars].reverse();
  for (const event of events) {
    // Use the actual observation time, never an earlier pivot or occurrence time.
    const observedAt = Date.parse(event.observed_at);
    const bar = newestBars.find(row => row.timestamp <= observedAt);
    if (!bar || observedAt - bar.timestamp > 120_000) continue;
    const group = grouped.get(bar.timestamp) ?? { bar, events: [] };
    group.events.push(event);
    grouped.set(bar.timestamp, group);
  }
  return [...grouped.values()].map(({ bar, events }) => {
    // One marker per minute, showing its latest observation; retain every event for inspection.
    const sorted = [...events].sort((a, b) => Date.parse(b.observed_at) - Date.parse(a.observed_at) || b.quality_score - a.quality_score);
    const event = sorted[0]!;
    return {
      name: 'intradayPattern', id: `intraday-pattern-${bar.timestamp}`, groupId: 'intraday-patterns', lock: true,
      points: [{ timestamp: bar.timestamp, value: directionOf(event.direction) === 'bullish' ? bar.low : bar.high }],
      extendData: { event, dark }, onClick: () => { onSelect(sorted); return true; },
    };
  });
}
