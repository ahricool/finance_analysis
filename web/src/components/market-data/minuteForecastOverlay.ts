import { registerOverlay } from 'klinecharts';
import { hoverOnly, type ChartAnnotation } from './chartAnnotation';
import type { ForecastBar, MinuteForecast } from '@/api/minuteForecast';

let registered = false;
export const MINUTE_FORECAST_OVERLAY_ID = 'minute-forecast';

export function minuteForecastOverlay(forecast: MinuteForecast, future: ForecastBar[], dark: boolean): ChartAnnotation {
  if (!registered) {
    registered = true;
    registerOverlay<{ color: string }>({
      name: MINUTE_FORECAST_OVERLAY_ID,
      totalStep: 2,
      needDefaultPointFigure: false,
      needDefaultXAxisFigure: false,
      needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates, overlay, bounding }) => {
        const anchor = coordinates[0];
        if (!anchor || coordinates.length < 2) return [];
        const color = overlay.extendData.color;
        return [{
          type: 'line',
          attrs: { coordinates: [{ x: anchor.x, y: 0 }, { x: anchor.x, y: bounding.height }] },
          styles: { color, style: 'dashed', size: 1.5, dashedValue: [3, 5] },
          ignoreEvent: hoverOnly,
        }, {
          type: 'line', attrs: { coordinates },
          styles: { color, style: 'dashed', size: 2, dashedValue: [5, 4] },
          ignoreEvent: hoverOnly,
        }];
      },
    });
  }
  return {
    name: MINUTE_FORECAST_OVERLAY_ID,
    id: MINUTE_FORECAST_OVERLAY_ID,
    lock: true, fixedZLevel: true, zLevel: 1,
    hint: `${forecast.closeReplay ? 'Kronos 收盘试算' : 'Kronos 分钟线预测'} · 竖虚线标出预测起点，折线连接各分钟的预测收盘价`,
    points: [{ timestamp: forecast.anchor, value: forecast.anchorClose },
      ...future.map(bar => ({ timestamp: bar.timestamp, value: bar.close }))],
    extendData: { color: dark ? '#93c5fd' : '#1d4ed8' },
  };
}
