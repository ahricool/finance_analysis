<script setup lang="ts">
import { computed } from 'vue';
import { use } from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import { useTheme } from '@/composables/useTheme';
import type { Metrics } from '@/api/stockStrategies';

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent]);
const props = defineProps<{ items: Metrics[]; benchmark: string }>();
const { resolvedTheme } = useTheme();
const option = computed(() => {
  const muted = resolvedTheme.value === 'dark' ? '#a9afbd' : '#667085';
  const split = resolvedTheme.value === 'dark' ? 'rgba(255,255,255,.1)' : 'rgba(15,23,42,.08)';
  const dates = props.items.map(r => r.tradeDate);
  return {
    animation: false,
    color: ['#df7997', '#8b95a8', '#d59b55'],
    tooltip: { trigger: 'axis', valueFormatter: (v: number | null) => v == null ? '—' : `${v.toFixed(2)}%` },
    legend: { top: 0, textStyle: { color: muted } },
    grid: [{ left: 62, right: 40, top: 45, height: '48%' }, { left: 62, right: 40, top: '68%', height: '17%' }],
    xAxis: [0, 1].map(gridIndex => ({ type: 'category', gridIndex, data: dates, boundaryGap: false,
      axisLabel: { color: muted, hideOverlap: true, formatter: (value: string) => value.slice(5) }, axisLine: { lineStyle: { color: split } } })),
    yAxis: [0, 1].map(gridIndex => ({ type: 'value', gridIndex, axisLabel: { color: muted, formatter: '{value}%' },
      splitLine: { lineStyle: { color: split } } })),
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }, { type: 'slider', xAxisIndex: [0, 1], bottom: 0, height: 18 }],
    series: [
      { name: '策略累计收益', type: 'line', showSymbol: props.items.length === 1, data: props.items.map(r => r.totalReturn * 100) },
      { name: `${props.benchmark} 同起点`, type: 'line', showSymbol: false, connectNulls: false,
        data: props.items.map(r => r.benchmarkReturn == null ? null : r.benchmarkReturn * 100), lineStyle: { type: 'dashed' } },
      { name: '收盘回撤', type: 'line', xAxisIndex: 1, yAxisIndex: 1, showSymbol: false,
        data: props.items.map(r => r.drawdown * 100), areaStyle: { opacity: .15 } },
    ],
  };
});
</script>

<template>
  <div
    class="h-[420px] w-full"
    data-testid="strategy-performance-chart"
  >
    <VChart
      class="h-full w-full"
      :option="option"
      autoresize
      aria-label="策略累计收益、同起点基准和收盘回撤曲线"
    />
  </div>
</template>
