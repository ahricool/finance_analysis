import type { Chart, OverlayCreate, OverlayFigure } from 'klinecharts';

export type ChartAnnotation = OverlayCreate & { hint?: string };

// gapBar is the rendered candle body, while bar includes the gutter.
export function markerWidth(chart: Chart) {
  return Math.max(11, chart.getBarSpace().gapBar + 3);
}

// Leave navigation gestures to the chart and keep read-only annotations on right click.
export const hoverOnly: OverlayFigure['ignoreEvent'] = [
  'onClick', 'onDoubleClick', 'onRightClick', 'onSelected', 'onDeselected',
];
