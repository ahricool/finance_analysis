import { registerOverlay, type OverlayCreate } from 'klinecharts';
import type { IntradayBar } from '@/api/intradayMarket';
import type { WindowScore } from '@/api/intradayOptions';

let registered = false;
export function referenceSeries(bars: IntradayBar[], mode: 'vwap' | 'mean') {
  let numerator = 0, denominator = 0;
  const exact = mode === 'vwap' && bars.every(bar => bar.turnover != null);
  const points: Array<{ timestamp: number; value: number }> = [];
  // Never bridge missing minutes or claim a partial-day average is a full-session VWAP.
  const gap = bars.some((bar, i) => bar.partial || (i > 0 && bar.timestamp - bars[i - 1]!.timestamp !== 60_000));
  if (gap) return { points, label: '分钟缺失，均价参考暂停' };
  for (const bar of bars) {
    if (mode === 'mean') { numerator += bar.close; denominator++; }
    else {
      numerator += exact ? bar.turnover! : (bar.high + bar.low + bar.close) / 3 * bar.volume;
      denominator += bar.volume;
    }
    if (denominator > 0) points.push({ timestamp: bar.timestamp, value: numerator / denominator });
  }
  return { points, label: mode === 'mean' ? '已采集分钟收盘价等权均价' : exact ? '已采集区间VWAP = 累计成交额 / 累计成交量' : '已采集区间近似VWAP = Σ(HLC3 × 分钟成交量) / Σ成交量' };
}
export function trendOverlays(bars: IntradayBar[], window: WindowScore | undefined, mode: 'vwap' | 'mean' | 'off', dark: boolean): OverlayCreate[] {
  if (!registered) {
    registerOverlay({ name: 'optionsReference', totalStep: 1, needDefaultPointFigure: false,
      needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates }) => coordinates.length < 2 ? [] : [{ type: 'line', ignoreEvent: true,
        attrs: { coordinates }, styles: { color: '#c084fc', size: 1.5 } }],
    });
    registerOverlay<{ dark: boolean }>({ name: 'optionsWindow', totalStep: 1, needDefaultPointFigure: false,
      needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates, bounding, overlay }) => {
        const a = coordinates[0], b = coordinates[1];
        if (!a || !b) return [];
        return [{ type: 'rect', ignoreEvent: true, attrs: { x: a.x, y: 0, width: Math.max(1, b.x - a.x), height: bounding.height },
          styles: { style: 'fill', color: overlay.extendData.dark ? 'rgba(168,85,247,0.12)' : 'rgba(168,85,247,0.07)' } }];
      },
    });
    registered = true;
  }
  const result: OverlayCreate[] = [];
  if (window?.startAt && window.endAt && bars.length) result.push({ name: 'optionsWindow', id: 'options-window', lock: true,
    points: [{ timestamp: Date.parse(window.startAt), value: bars[0]!.close },
      { timestamp: Date.parse(window.endAt) - 60_000, value: bars[0]!.close }], extendData: { dark } });
  if (mode !== 'off') {
    const { points } = referenceSeries(bars, mode);
    if (points.length) result.push({ name: 'optionsReference', id: 'options-reference', lock: true, points });
  }
  return result;
}
