import type { IndustryHistory, IndustrySnapshot } from '@/api/industryStrength';
import {
  bubbleSize,
  formatPoints,
  formatPulse,
  formatScore,
  heatmapMissingColor,
  heatmapNormalizedRank,
  selectedDateLeaders,
  stateColors,
  stateLabels,
} from './display';

type Theme = 'light' | 'dark';

export function matrixLabel(row: IndustrySnapshot, selected: string): { show: boolean; position: 'top' | 'bottom' | 'left' | 'right' } {
  const active = Boolean(selected) && row.industryCode === selected;
  if (selected) {
    return { show: active, position: matrixLabelPosition(row) };
  }
  if (row.strengthRank === 1) return { show: true, position: 'top' };
  if (row.strengthRank === 2) return { show: true, position: 'bottom' };
  if (row.strengthRank === 3) return { show: true, position: 'left' };
  return { show: false, position: matrixLabelPosition(row) };
}

function matrixLabelPosition(row: IndustrySnapshot): 'top' | 'bottom' | 'left' | 'right' {
  if (row.strengthScore >= 82) return 'left';
  if (row.strengthScore <= 18) return 'right';
  if ((row.momentumAcceleration5D ?? 0) < 0) return 'bottom';
  return 'top';
}

function quadrantLabel(text: string, fill: string, theme: Theme, extra: Record<string, string>) {
  return {
    type: 'text' as const,
    silent: true,
    ...extra,
    style: {
      text,
      fill,
      fontSize: 11,
      backgroundColor: theme === 'dark' ? 'rgba(24,24,27,0.72)' : 'rgba(255,255,255,0.78)',
      padding: [3, 5],
    },
  };
}

export function matrixOption(rows: IndustrySnapshot[], selected: string, theme: Theme) {
  const text = theme === 'dark' ? '#d4d4d8' : '#52525b';
  const muted = theme === 'dark' ? '#a1a1aa' : '#71717a';
  const gridLine = theme === 'dark' ? '#3f3f46' : '#e4e4e7';
  const colors = stateColors(theme);
  const selectedRow = rows.find((row) => row.industryCode === selected);
  return {
    animation: false,
    grid: { top: 40, right: 64, bottom: 60, left: 76, containLabel: true },
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (params: { data: { name: string; state: keyof typeof stateLabels; value: number[] } }) => {
        const data = params.data;
        return [
          `${data.name} · ${stateLabels[data.state]}`,
          `综合强度 ${formatScore(data.value[0])}`,
          `5 日动量变化 ${formatPoints((data.value[1] ?? 0) / 100)}`,
          `成交额脉冲 ${formatPulse(data.value[2])}`,
        ].join('<br/>');
      },
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: 100,
      name: '综合强度',
      nameLocation: 'middle',
      nameGap: 28,
      nameTextStyle: { color: text },
      axisLabel: { color: text },
      splitLine: { lineStyle: { color: gridLine } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      name: '5 日动量变化（百分点）',
      nameTextStyle: { color: text },
      axisLabel: { color: text },
      splitLine: { lineStyle: { color: gridLine } },
    },
    graphic: [
      quadrantLabel('低强度但改善', muted, theme, { left: '20%', top: '16%' }),
      quadrantLabel('高强度且加速', muted, theme, { right: '18%', top: '16%' }),
      quadrantLabel('低强度且恶化', muted, theme, { left: '20%', bottom: '20%' }),
      quadrantLabel('高强度但降速', muted, theme, { right: '18%', bottom: '20%' }),
    ],
    series: [{
      type: 'scatter',
      symbolSize: (value: number[]) => bubbleSize(value[2] ?? 0),
      labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
      data: rows.map((row) => {
        const active = row.industryCode === selected;
        const label = matrixLabel(row, selected);
        return {
          name: row.industryName,
          code: row.industryCode,
          state: row.state,
          value: [row.strengthScore, row.momentumAcceleration5D * 100, row.turnoverRatio5D],
          itemStyle: {
            color: colors[row.state],
            opacity: selected && !active ? 0.28 : 0.88,
            borderWidth: active ? 3 : 1,
            borderColor: active ? text : 'rgba(255,255,255,0.35)',
          },
          label: {
            show: label.show,
            formatter: row.industryName,
            position: label.position,
            distance: 8,
            color: text,
            fontSize: 11,
          },
          emphasis: { scale: true, itemStyle: { opacity: 1, borderWidth: 3 } },
        };
      }),
      markLine: {
        silent: true,
        symbol: 'none',
        label: { show: false },
        lineStyle: { color: muted, type: 'dashed' },
        data: [{ xAxis: 50 }, { yAxis: 0 }],
      },
    }],
    selectedName: selectedRow?.industryName ?? '',
  };
}

export type HeatmapCell = {
  code: string;
  name: string;
  date: string;
  rank: number | null;
  rankedCount: number | null;
  missing: boolean;
  value: [number, number, number | string];
  itemStyle?: { color?: string; borderWidth?: number; borderColor?: string };
};

export function heatmapCells(
  rows: IndustrySnapshot[],
  history: IndustryHistory,
  selected: string,
  theme: Theme,
): { leaders: IndustrySnapshot[]; dates: string[]; cells: HeatmapCell[] } {
  const leaders = selectedDateLeaders(rows);
  const missing = theme === 'dark' ? heatmapMissingColor.dark : heatmapMissingColor.light;
  const accent = theme === 'dark' ? '#fafafa' : '#171717';
  const byKey = new Map(history.items.map((item) => [`${item.industryCode}:${item.tradeDate}`, item]));
  const cells: HeatmapCell[] = [];
  leaders.forEach((leader, y) => {
    history.dates.forEach((date, x) => {
      const item = byKey.get(`${leader.industryCode}:${date}`);
      const selectedRow = leader.industryCode === selected;
      if (!item) {
        cells.push({
          code: leader.industryCode,
          name: leader.industryName,
          date,
          rank: null,
          rankedCount: null,
          missing: true,
          value: [x, y, '-'],
          itemStyle: {
            color: missing,
            borderWidth: selectedRow ? 2 : 1,
            borderColor: selectedRow ? accent : 'transparent',
          },
        });
        return;
      }
      cells.push({
        code: item.industryCode,
        name: item.industryName,
        date,
        rank: item.strengthRank,
        rankedCount: item.quality.rankedCount,
        missing: false,
        value: [x, y, heatmapNormalizedRank(item.strengthRank, item.quality.rankedCount)],
        itemStyle: {
          borderWidth: selectedRow ? 2 : 1,
          borderColor: selectedRow ? accent : 'transparent',
        },
      });
    });
  });
  return { leaders, dates: history.dates, cells };
}

export function heatmapOption(rows: IndustrySnapshot[], history: IndustryHistory, selected: string, theme: Theme) {
  const text = theme === 'dark' ? '#d4d4d8' : '#52525b';
  const { leaders, dates, cells } = heatmapCells(rows, history, selected, theme);
  const selectedInSample = leaders.some((row) => row.industryCode === selected);
  return {
    animation: false,
    grid: { top: 16, right: 24, bottom: 72, left: 108, containLabel: false },
    tooltip: {
      confine: true,
      formatter: (params: { data: HeatmapCell }) => {
        const cell = params.data;
        if (cell.missing) {
          return `${cell.name}<br/>${cell.date}<br/>该日无该行业快照`;
        }
        return [
          cell.name,
          cell.date,
          `当日排名 ${cell.rank}`,
          `当日有效行业数 ${cell.rankedCount}`,
        ].join('<br/>');
      },
    },
    xAxis: {
      type: 'category',
      data: dates.map((date) => date.slice(5)),
      axisLabel: { color: text, hideOverlap: true },
      splitArea: { show: true },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: leaders.map((row) => row.industryName),
      axisLabel: {
        color: text,
        width: 96,
        overflow: 'truncate',
        formatter: (name: string, index: number) => {
          const row = leaders[index];
          return selectedInSample && row?.industryCode === selected ? `{active|${name}}` : name;
        },
        rich: { active: { fontWeight: 700, color: text } },
      },
      splitArea: { show: true },
    },
    visualMap: {
      min: 0,
      max: 100,
      orient: 'horizontal',
      left: 'center',
      bottom: 8,
      text: ['强（排名靠前）', '弱（排名靠后）'],
      textStyle: { color: text },
      inRange: { color: theme === 'dark' ? ['#0f766e', '#3f3f46', '#e11d48'] : ['#0f766e', '#f4f4f5', '#e11d48'] },
      formatter: (value: number) => `${Math.round(value)}`,
    },
    series: [{
      type: 'heatmap',
      data: cells,
      itemStyle: { borderWidth: 1, borderColor: theme === 'dark' ? '#171717' : '#fff' },
    }],
    snapshotDays: dates.length,
    selectedInSample,
  };
}

export const bubbleLegendSamples = [0.5, 1, 2];
