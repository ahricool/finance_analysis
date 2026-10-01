import { registerOverlay, type OverlayCreate } from 'klinecharts';
import type { DailyBar } from '@/api/marketData';
import type { DailyPatternEvent, DailyPatternType } from '@/utils/dailyPatterns';

const labels: Record<DailyPatternType, string> = {
  bullish_engulfing: '↑ 吞没', bearish_engulfing: '↓ 吞没', hammer: '↑ 锤子',
  shooting_star: '↓ 射星', morning_star: '↑ 晨星', evening_star: '↓ 黄昏',
};
let registered = false;
export function dailyPatternOverlays(
  events: DailyPatternEvent[], bars: readonly DailyBar[], dark: boolean,
  onSelect: (event: DailyPatternEvent) => void,
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
        return [{ type: 'text', attrs: { x: point.x, y: Math.max(10, Math.min(bounding.height - 10, point.y + (bullish ? 22 : -52))),
          text: `${labels[event.type]}${event.confirmed ? '' : ' · 形成中'}`, align: 'center', baseline: 'middle' },
        styles: { color: bullish ? (event.dark ? '#e86464' : '#dc2626') : (event.dark ? '#39b77a' : '#16854e'),
          size: 12, weight: event.confirmed ? 'bold' : 'normal',
          backgroundColor: event.dark ? '#171717' : '#ffffff', paddingLeft: 3, paddingRight: 3 } }];
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
      extendData: { ...event, dark }, onClick: () => { onSelect(event); return true; } }];
  });
}
