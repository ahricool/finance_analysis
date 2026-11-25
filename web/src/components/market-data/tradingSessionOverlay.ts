import { registerOverlay } from 'klinecharts';
import type { IntradayBar, TradeSession } from '@/api/intradayMarket';
import type { ChartAnnotation } from './chartAnnotation';

export const sessionStyles = {
  pre: { label: '盘前', color: '#d97706', fill: 'rgba(217,119,6,0.13)' },
  regular: { label: '盘中', color: '#64748b', fill: 'transparent' },
  post: { label: '盘后', color: '#0284c7', fill: 'rgba(2,132,199,0.13)' },
  overnight: { label: '夜盘', color: '#8b5cf6', fill: 'rgba(139,92,246,0.15)' },
} as const;

let registered = false;
export function tradingSessionOverlays(bars: readonly IntradayBar[]): ChartAnnotation[] {
  if (!registered) {
    registerOverlay<{ session: TradeSession }>({ name: 'stockTradingSession', totalStep: 2,
      needDefaultPointFigure: false, needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates, bounding, overlay, chart }) => {
        const [first, last] = coordinates;
        if (!first || !last) return [];
        const half = chart.getBarSpace().bar / 2;
        const left = Math.max(0, first.x - half), right = Math.min(bounding.width, last.x + half);
        if (right <= left) return [];
        const style = sessionStyles[overlay.extendData.session];
        return [
          { type: 'rect', ignoreEvent: true, attrs: { x: left, y: 0, width: right - left, height: bounding.height },
            styles: { style: 'fill', color: style.fill } },
          { type: 'rect', ignoreEvent: true, attrs: { x: left, y: 0, width: right - left, height: 3 },
            styles: { style: 'fill', color: style.color } },
        ];
      },
    });
    registered = true;
  }
  const groups: { session: TradeSession; first: IntradayBar; last: IntradayBar }[] = [];
  for (const bar of bars) {
    if (!bar.tradeSession) continue;
    const previous = groups.at(-1);
    if (previous?.session === bar.tradeSession) previous.last = bar;
    else groups.push({ session: bar.tradeSession, first: bar, last: bar });
  }
  return groups.map(({ session, first, last }) => ({ name: 'stockTradingSession', id: `session-${first.timestamp}`,
    groupId: 'trading-sessions', lock: true, fixedZLevel: true, zLevel: -10,
    points: [{ timestamp: first.timestamp, value: first.close }, { timestamp: last.timestamp, value: last.close }],
    extendData: { session } }));
}
