import { registerOverlay, type OverlayFigure } from 'klinecharts';
import { hoverOnly, type ChartAnnotation } from './chartAnnotation';
import { readMarketCanvasColors } from '@/utils/marketColors';

type ForecastCandle = { timestamp: number; open: number; high: number; low: number; close: number };

let registered = false;
const OVERLAY_NAME = 'kronos-forecast-candles';
export const MINUTE_FORECAST_OVERLAY_ID = 'minute-forecast';
export const DAILY_FORECAST_OVERLAY_ID = 'daily-forecast';

export function forecastOverlay(
  id: string, label: string, future: ForecastCandle[], dark: boolean,
): ChartAnnotation {
  if (!registered) {
    registered = true;
    registerOverlay<{ colors: string[] }>({
      name: OVERLAY_NAME,
      totalStep: 2,
      needDefaultPointFigure: false,
      needDefaultXAxisFigure: false,
      needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates, overlay, chart }) => {
        const halfWidth = Math.max(1, chart.getBarSpace().halfGapBar);
        const figures: OverlayFigure[] = [];
        for (const [index, color] of overlay.extendData.colors.entries()) {
          const [open, high, low, close] = coordinates.slice(index * 4, (index + 1) * 4);
          if (!open || !high || !low || !close) continue;
          const x = open.x;
          const top = Math.min(open.y, close.y);
          const bottom = Math.max(top + 2, open.y, close.y);
          const left = x - halfWidth;
          const right = x + halfWidth;
          figures.push({
            type: 'line',
            attrs: [
              { coordinates: [{ x, y: Math.min(high.y, top) }, { x, y: top }] },
              { coordinates: [{ x, y: bottom }, { x, y: Math.max(bottom, low.y) }] },
            ],
            styles: { color, size: 1 },
            ignoreEvent: hoverOnly,
          }, {
            type: 'line',
            attrs: { coordinates: [
              { x: left, y: top }, { x: right, y: top }, { x: right, y: bottom },
              { x: left, y: bottom }, { x: left, y: top },
            ] },
            styles: { color, style: 'solid', size: 1 },
            ignoreEvent: hoverOnly,
          });
        }
        return figures;
      },
    });
  }
  const { up, down, muted } = readMarketCanvasColors(dark);
  return {
    name: OVERLAY_NAME,
    id,
    lock: true, fixedZLevel: true, zLevel: 1,
    hint: `${label} · 空心蜡烛为预测开高低收`,
    points: future.flatMap(({ timestamp, open, high, low, close }) =>
      [open, high, low, close].map(value => ({ timestamp, value }))),
    extendData: { colors: future.map(bar => bar.close === bar.open ? muted : bar.close > bar.open ? up : down) },
  };
}
