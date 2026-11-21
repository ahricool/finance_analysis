import { registerOverlay } from 'klinecharts';
import type { IntradayBar } from '@/api/intradayMarket';
import { markerWidth, hoverOnly, type ChartAnnotation } from '@/components/market-data/chartAnnotation';
import { clock, fmt, structureName, structurePhases } from './labels';
import type { IntradayStructure, WindowScore } from '@/api/intradayOptions';

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
export function trendOverlays(bars: IntradayBar[], window: WindowScore | undefined, mode: 'vwap' | 'mean' | 'off', dark: boolean): ChartAnnotation[] {
  if (!registered) {
    registerOverlay({ name: 'optionsReference', totalStep: 1, needDefaultPointFigure: false,
      needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates }) => coordinates.length < 2 ? [] : [{ type: 'line', ignoreEvent: hoverOnly,
        attrs: { coordinates }, styles: { color: '#c084fc', size: 2 } }],
    });
    registerOverlay<{ dark: boolean }>({ name: 'optionsWindow', totalStep: 1, needDefaultPointFigure: false,
      needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates, bounding, overlay }) => {
        const a = coordinates[0], b = coordinates[1];
        if (!a || !b) return [];
        return [{ type: 'rect', ignoreEvent: hoverOnly, attrs: { x: a.x, y: 0, width: Math.max(1, b.x - a.x), height: bounding.height },
          styles: { style: 'fill', color: overlay.extendData.dark ? 'rgba(168,85,247,0.12)' : 'rgba(168,85,247,0.07)' } }];
      },
    });
    registered = true;
  }
  const result: ChartAnnotation[] = [];
  if (window?.startAt && window.endAt && bars.length) result.push({ name: 'optionsWindow', id: 'options-window', lock: true, fixedZLevel: true, zLevel: 0,
    hint: `观察窗口 · ${window.minutes} 分钟（${clock(window.startAt)}–${clock(window.endAt)}）`,
    points: [{ timestamp: Date.parse(window.startAt), value: bars[0]!.close },
      { timestamp: Date.parse(window.endAt) - 60_000, value: bars[0]!.close }], extendData: { dark } });
  if (mode !== 'off') {
    const { points, label } = referenceSeries(bars, mode);
    if (points.length) result.push({ name: 'optionsReference', id: 'options-reference', lock: true, fixedZLevel: true, zLevel: 1, points, hint: label });
  }
  return result;
}

let structureRegistered = false;
export function structureOverlays(structure: IntradayStructure | null | undefined): ChartAnnotation[] {
  if (!structure) return [];
  if (!structureRegistered) {
    registerOverlay({ name: 'optionsBoxEdge', totalStep: 1, needDefaultPointFigure: false,
      needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates }) => [{ type: 'line', ignoreEvent: hoverOnly,
        attrs: { coordinates }, styles: { color: '#f59e0b', size: 2 } }],
    });
    registerOverlay<{ shape: 'diamond' | 'high' | 'low' }>({
      name: 'optionsStructureMark', totalStep: 1, needDefaultPointFigure: false,
      needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates, overlay, chart, bounding }) => {
        if (!coordinates[0]) return [];
        const { x, y } = coordinates[0];
        if (y < 0 || y > bounding.height) return [];
        const half = markerWidth(chart) / 2;
        const shape = overlay.extendData.shape;
        // Leave a small gap to the wick or box edge and keep the whole mark visible.
        const offset = shape === 'low' ? half + 3 : -half - 3;
        const cy = Math.min(bounding.height - half, Math.max(half, y + offset));
        const tip = shape === 'low' ? -half : half;
        const vertices = shape === 'diamond'
          ? [{ x, y: cy - half }, { x: x + half, y: cy }, { x, y: cy + half }, { x: x - half, y: cy }]
          : [{ x, y: cy + tip }, { x: x + half, y: cy - tip }, { x: x - half, y: cy - tip }];
        return [{ type: 'polygon', attrs: { coordinates: vertices }, ignoreEvent: hoverOnly,
          styles: { style: 'fill', color: '#f59e0b' } }];
      },
    });
    structureRegistered = true;
  }
  const result: ChartAnnotation[] = structure.pivots.map(pivot => ({
    name: 'optionsStructureMark', id: `structure-pivot-${pivot.kind}-${pivot.at}`, lock: true, fixedZLevel: true, zLevel: 3,
    points: [{ timestamp: Date.parse(pivot.at), value: pivot.price }], extendData: { shape: pivot.kind },
    hint: `已确认${pivot.kind === 'high' ? '高点' : '低点'} · ${fmt(pivot.price, 2)}，${clock(pivot.at)} 出现，${clock(pivot.confirmedAt)} 确认`,
  }));
  if (structure.box) {
    const box = structure.box;
    if (['breakout_up', 'breakout_down', 'failed_up', 'failed_down'].includes(structure.kind)) {
      // since is the current phase close time, not the original breakout confirmation.
      const phaseBarTime = Date.parse(structure.since) - 60_000;
      const up = structure.kind.endsWith('_up');
      const boundary = up ? box.upper : box.lower;
      result.push({ name: 'optionsStructureMark', id: 'structure-event', lock: true, fixedZLevel: true, zLevel: 4,
        points: [{ timestamp: phaseBarTime, value: boundary }], extendData: { shape: 'diamond' },
        hint: `${structureName(structure)} · ${structurePhases[structure.phase]}，${clock(structure.since)} 收盘，箱体${up ? '上' : '下'}沿 ${fmt(boundary, 2)}`,
      });
    }
    for (const [key, value] of [['upper', box.upper], ['lower', box.lower]] as const) {
      result.push({ name: 'optionsBoxEdge', id: `structure-box-${key}`, lock: true, fixedZLevel: true, zLevel: 2,
        hint: `箱体${key === 'upper' ? '上' : '下'}沿 · ${fmt(value, 2)}，取自 ${clock(box.startAt)}–${clock(box.endAt)} 的固定区间`,
        points: [{ timestamp: Date.parse(box.startAt), value }, { timestamp: Date.parse(structure.asOf) - 60_000, value }],
      });
    }
  }
  return result;
}
