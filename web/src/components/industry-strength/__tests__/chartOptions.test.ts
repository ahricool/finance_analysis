import { afterEach, describe, expect, it } from 'vitest';
import { init, use } from 'echarts/core';
import { CustomChart, HeatmapChart, ScatterChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, VisualMapComponent, MarkLineComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
import type { IndustrySnapshot } from '@/api/industryStrength';
import { heatmapCells, heatmapOption, matrixLabel, matrixOption, visibleQuadrantLabels } from '../chartOptions';
import { bubbleSize } from '../display';

use([ScatterChart, HeatmapChart, CustomChart, GridComponent, TooltipComponent, VisualMapComponent, MarkLineComponent, SVGRenderer]);

function row(overrides: Partial<IndustrySnapshot> = {}): IndustrySnapshot {
  return {
    tradeDate: '2026-09-16', industryCode: '881101.TI', industryName: '半导体', state: 'STRONG', close: 100,
    strengthRank: 1, strengthScore: 88, ret1D: 0.01, ret5D: 0.03, ret10D: 0.04, ret20D: 0.05,
    rs5D: 0.01, rs10D: 0.02, rs20D: 0.03, rankChange1D: 2, rankChange3D: 5, rankChange5D: null,
    previous5DReturn: 0.01, momentumAcceleration5D: 0.02, accelerationPercentile: 80, turnoverRatio5D: 1.5,
    upRatio: 0.7, aboveMa5Ratio: 0.8, aboveMa20Ratio: 0.9, equalWeightReturn: 0.01,
    constituentCount: 10, dailyValidCount: 10, ma5ValidCount: 10, aboveMa5Count: 8, ma20ValidCount: 10, aboveMa20Count: 9,
    upCount: 7, downCount: 2, flatCount: 1,
    dataTimestamp: '2026-09-16T07:00:00Z', membersObservedAt: '2026-09-16T11:00:00Z',
    createdAt: '2026-09-16T11:05:00Z', updatedAt: '2026-09-16T11:05:00Z',
    quality: { dailyBreadthCoverage: 1, ma5Coverage: 1, ma20Coverage: 1, catalogCount: 2, rankedCount: 10, coverage: 1, excluded: {} },
    ...overrides,
  };
}

const charts: { dispose: () => void }[] = [];
afterEach(() => {
  while (charts.length) charts.pop()?.dispose();
  document.body.replaceChildren();
});

describe('industry strength charts', () => {
  it('labels only the selected industry, or staggers top-3 labels when none is selected', () => {
    const rows = [
      row({ industryCode: '1.TI', industryName: '半导体', strengthRank: 1, strengthScore: 98 }),
      row({ industryCode: '2.TI', industryName: '通信设备', strengthRank: 2, strengthScore: 94, momentumAcceleration5D: 0.04 }),
      row({ industryCode: '3.TI', industryName: '电力设备', strengthRank: 3, strengthScore: 90 }),
      row({ industryCode: '4.TI', industryName: '银行', strengthRank: 4, strengthScore: 40 }),
    ];
    expect(matrixLabel(rows[0], '')).toEqual({ show: true, position: 'top' });
    expect(matrixLabel(rows[1], '')).toEqual({ show: true, position: 'bottom' });
    expect(matrixLabel(rows[2], '')).toEqual({ show: true, position: 'left' });
    expect(matrixLabel(rows[3], '').show).toBe(false);
    expect(matrixLabel(rows[0], '2.TI').show).toBe(false);
    expect(matrixLabel(rows[1], '2.TI')).toEqual({ show: true, position: 'left' });
  });

  it('maps bubble size with the same formula used by the legend', () => {
    const option = matrixOption([row()], '881101.TI', 'light');
    const series = option.series[0] as { symbolSize: (value: number[]) => number };
    expect(series.symbolSize([88, 2, 1.5])).toBe(bubbleSize(1.5));
    expect(option.xAxis.name).toBe('综合强度');
    expect(option.yAxis.name).toContain('百分点');
  });

  it('renders tooltips as rich text so names like A<B&C> are not HTML', () => {
    const named = row({ industryName: 'A<B&C>' });
    const matrix = matrixOption([named], named.industryCode, 'light');
    expect(matrix.tooltip.renderMode).toBe('richText');
    const matrixText = matrix.tooltip.formatter({
      data: { name: 'A<B&C>', state: 'STRONG', value: [88, 2, 1.5] },
    });
    expect(matrixText).toContain('A<B&C>');
    expect(matrixText).not.toMatch(/<br\s*\/?>/i);
    expect(matrixText).not.toMatch(/<script/i);

    const leaders = [named, row({ industryCode: '881102.TI', industryName: 'A<B&C>银行', strengthRank: 2 })];
    const history = { dates: ['2026-09-16'], items: [named] };
    const heat = heatmapOption(leaders, history, named.industryCode, 'light');
    expect(heat.tooltip.renderMode).toBe('richText');
    const missing = heatmapCells(leaders, history, named.industryCode, 'light').missing[0]!;
    const heatText = heat.tooltip.formatter({ data: missing });
    expect(heatText).toContain('A<B&C>银行');
    expect(heatText).toContain('该日无该行业快照');
    expect(heatText).not.toMatch(/<br\s*\/?>/i);
  });

  it('places quadrant labels in data coordinates and hides quadrants outside the y range', () => {
    const allPositive = [row({ momentumAcceleration5D: 0.01 }), row({ industryCode: '2.TI', strengthScore: 20, momentumAcceleration5D: 0.04 })];
    const positive = visibleQuadrantLabels(allPositive).map((item) => item.text);
    expect(positive).toEqual(['低强度但改善', '高强度且加速']);
    expect(visibleQuadrantLabels(allPositive).every((item) => item.y > 0)).toBe(true);

    const allNegative = [row({ momentumAcceleration5D: -0.01 }), row({ industryCode: '2.TI', strengthScore: 20, momentumAcceleration5D: -0.04 })];
    const negative = visibleQuadrantLabels(allNegative).map((item) => item.text);
    expect(negative).toEqual(['低强度且恶化', '高强度但降速']);
    expect(visibleQuadrantLabels(allNegative).every((item) => item.y < 0)).toBe(true);

    const skewed = [
      row({ momentumAcceleration5D: 0.08 }),
      row({ industryCode: '2.TI', strengthScore: 20, momentumAcceleration5D: -0.01 }),
    ];
    const skewedLabels = visibleQuadrantLabels(skewed);
    expect(skewedLabels.map((item) => item.text)).toEqual([
      '低强度但改善', '高强度且加速', '低强度且恶化', '高强度但降速',
    ]);
    expect(skewedLabels.filter((item) => item.y > 0).every((item) => item.y > 0)).toBe(true);
    expect(skewedLabels.filter((item) => item.text.includes('恶化') || item.text.includes('降速')).every((item) => item.y < 0)).toBe(true);

    const crossed = [row({ momentumAcceleration5D: 0.03 }), row({ industryCode: '2.TI', strengthScore: 10, momentumAcceleration5D: -0.03 })];
    expect(visibleQuadrantLabels(crossed)).toHaveLength(4);
    expect(matrixOption(allPositive, '', 'light').quadrants.map((item) => item.text)).toEqual(positive);
  });

  it('keeps selected-day Top20 sample, missing style, and tooltip fields', () => {
    const leaders = [
      row(),
      row({ industryCode: '881102.TI', industryName: '银行', strengthRank: 2 }),
    ];
    const history = {
      dates: ['2026-09-15', '2026-09-16'],
      items: [row({ tradeDate: '2026-09-16' })],
    };
    const { cells, leaders: sample, missing, present } = heatmapCells(leaders, history, '881101.TI', 'light');
    expect(sample.map((item) => item.industryCode)).toEqual(['881101.TI', '881102.TI']);
    const missingCell = cells.find((cell) => cell.code === '881102.TI' && cell.date === '2026-09-15');
    expect(missingCell?.missing).toBe(true);
    expect(missingCell?.value).toEqual([0, 1]);
    expect(present.every((cell) => typeof cell.value[2] === 'number')).toBe(true);
    expect(missing.every((cell) => cell.value[2] === undefined)).toBe(true);
    const presentCell = cells.find((cell) => cell.code === '881101.TI' && cell.date === '2026-09-16');
    expect(presentCell).toMatchObject({ rank: 1, rankedCount: 10, date: '2026-09-16', missing: false });
    const tooltip = heatmapOption(leaders, history, '881101.TI', 'light').tooltip.formatter;
    expect(tooltip({ data: presentCell! })).toContain('半导体');
    expect(tooltip({ data: presentCell! })).toContain('2026-09-16');
    expect(tooltip({ data: presentCell! })).toContain('当日排名 1');
    expect(tooltip({ data: presentCell! })).toContain('当日有效行业数 10');
    expect(tooltip({ data: missingCell! })).toContain('该日无该行业快照');
  });

  it('does not enlarge the sample when the selected industry is outside Top20', () => {
    const rows = Array.from({ length: 21 }, (_, index) => row({
      industryCode: `${index}.TI`,
      industryName: `行业${index}`,
      strengthRank: index + 1,
    }));
    const { leaders } = heatmapCells(rows, { dates: ['2026-09-16'], items: rows }, '20.TI', 'light');
    expect(leaders).toHaveLength(20);
    expect(leaders.some((item) => item.industryCode === '20.TI')).toBe(false);
  });

    it('draws missing heatmap cells with ECharts without treating them as ranks', async () => {
    const leaders = [
      row(),
      row({ industryCode: '881102.TI', industryName: '银行', strengthRank: 2 }),
    ];
    const history = {
      dates: ['2026-09-15', '2026-09-16'],
      items: [row({ tradeDate: '2026-09-16' })],
    };
    const option = heatmapOption(leaders, history, '881102.TI', 'light');
    expect(option.visualMap.seriesIndex).toBe(0);
    expect(option.series[1]?.type).toBe('custom');
    expect(option.series[1]?.data.every((cell) => cell.missing && cell.value.length === 2)).toBe(true);

    const el = document.createElement('div');
    document.body.appendChild(el);
    const chart = init(el, undefined, { renderer: 'svg', width: 720, height: 360 });
    charts.push(chart);
    chart.setOption(option);
    await new Promise((resolve) => { setTimeout(resolve, 30); });
    const pixel = chart.convertToPixel({ seriesIndex: 1 }, [0, 1]);
    expect(pixel?.[0]).toBeGreaterThan(0);
    expect(pixel?.[1]).toBeGreaterThan(0);
    const svg = el.querySelector('svg');
    expect(svg).toBeTruthy();
    const markup = (svg?.innerHTML ?? '').toLowerCase();
    expect(markup).toMatch(/#d4d4d8|rgb\(\s*212\s*,\s*212\s*,\s*216\s*\)/);
    expect(option.series[0]?.data.every((cell) => !cell.missing)).toBe(true);
    const tooltip = option.tooltip.formatter({ data: option.series[1]!.data[0]! });
    expect(tooltip).toContain('该日无该行业快照');
    expect(tooltip).not.toMatch(/<br\s*\/?>/i);
  });
});
