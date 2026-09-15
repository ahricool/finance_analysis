import type { LineSeriesOption } from 'echarts/charts';
import type { GridComponentOption, LegendComponentOption, TooltipComponentOption } from 'echarts/components';
import type { ComposeOption } from 'echarts/core';
import type { TrendBreadthPoint } from '@/types/trendFollowing';

type Option = ComposeOption<LineSeriesOption | GridComponentOption | LegendComponentOption | TooltipComponentOption>;
export const percent = (value: number | null | undefined) => value == null ? '—' : `${(value * 100).toFixed(1)}%`;
export function delta5D(points: TrendBreadthPoint[], key: 'trendBreadth' | 'participation' | 'deteriorationBreadth') {
  const latest = points.at(-1)?.[key];
  const previous = points.at(-6)?.[key];
  if (latest == null || previous == null) return '—';
  const delta = (latest - previous) * 100;
  return `${delta > 0 ? '+' : ''}${delta.toFixed(1)}pp`;
}
export function breadthOption(points: TrendBreadthPoint[], dark: boolean, structure = false): Option {
  const green = dark ? '#34d399' : '#059669';
  const orange = dark ? '#fb923c' : '#c2410c';
  const colors = structure ? [dark ? '#52525b' : '#d4d4d8', dark ? '#a3e635' : '#65a30d', green, orange] : [green, orange];
  const series: Array<{ name: string; key: keyof TrendBreadthPoint }> = structure
    ? [{ name: 'Inactive · 未形成', key: 'inactive' }, { name: 'Emerging · 形成中', key: 'emerging' },
      { name: 'Healthy · 健康', key: 'healthy' }, { name: 'Deteriorating · 恶化', key: 'deteriorating' }]
    : [{ name: 'Trend Breadth', key: 'trendBreadth' }, { name: 'Deterioration', key: 'deteriorationBreadth' }];
  const text = dark ? '#d4d4d8' : '#52525b';
  return {
    animation: false, color: colors,
    grid: { left: 48, right: 22, top: 52, bottom: 32 },
    legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 8, textStyle: { color: text, fontSize: 11 }, selectedMode: !structure },
    tooltip: { trigger: 'axis', confine: true, renderMode: 'richText',
      backgroundColor: dark ? '#262626' : '#ffffff', borderColor: dark ? '#525252' : '#d4d4d4',
      textStyle: { color: dark ? '#fafafa' : '#171717' },
      valueFormatter: value => typeof value === 'number' ? `${value.toFixed(1)}%` : '—',
    },
    xAxis: { type: 'category', boundaryGap: false,
      data: points.map(point => `${point.tradeDate}${point.isPreview ? ' · Preview' : ''}`),
      axisLabel: { color: text, fontSize: 10, hideOverlap: true, showMaxLabel: true,
        formatter: (value: string) => value.includes('Preview') ? 'Preview' : value.slice(5).replace('-', '/') },
      axisLine: { lineStyle: { color: dark ? '#52525b' : '#d4d4d8' } }, axisTick: { show: false } },
    yAxis: { type: 'value', min: 0, max: 100, interval: 25,
      axisLabel: { color: text, fontSize: 10, formatter: '{value}%' },
      splitLine: { lineStyle: { color: dark ? '#3f3f46' : '#e4e4e7', type: 'dashed' } } },
    series: series.map(({ name, key }, index) => ({
      name, type: 'line', smooth: false, connectNulls: false, symbolSize: 7,
      showSymbol: points.length === 1 || points.some(point => point.isPreview),
      lineStyle: { width: structure ? 1 : 2.5, type: !structure && index === 1 ? 'dashed' : 'solid' },
      ...(structure ? { stack: 'structure', areaStyle: { opacity: 0.85 } } : {}),
      data: points.map(point => ({
        value: typeof point[key] === 'number' && (point.coverage ?? 0) <= 1 ? Number(point[key]) * 100 : null,
        symbol: point.isPreview ? 'emptyCircle' : 'circle',
        symbolSize: point.isPreview ? 9 : points.length === 1 ? 7 : 0,
      })),
    })),
  };
}
