<script setup lang="ts">
import { computed, ref } from 'vue';
import { use } from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import { Button } from '@/components/ui/button';
import { useTheme } from '@/composables/useTheme';
import type { Metrics } from '@/api/stockStrategies';

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent]);
const props = defineProps<{ items: Metrics[]; benchmark: string }>();
const { resolvedTheme } = useTheme();
const range = ref(0);
const option = computed(() => {
  const muted = resolvedTheme.value === 'dark' ? '#a9afbd' : '#667085';
  const split = resolvedTheme.value === 'dark' ? 'rgba(255,255,255,.1)' : 'rgba(15,23,42,.08)';
  const dates = props.items.map(r => r.tradeDate);
  const last = dates.at(-1);
  const cutoff = last ? new Date(`${last}T00:00:00Z`) : null;
  if (cutoff) {
    const day = cutoff.getUTCDate();
    cutoff.setUTCDate(1);
    cutoff.setUTCMonth(cutoff.getUTCMonth() - range.value);
    const daysInMonth = new Date(Date.UTC(cutoff.getUTCFullYear(), cutoff.getUTCMonth() + 1, 0)).getUTCDate();
    cutoff.setUTCDate(Math.min(day, daysInMonth));
  }
  const first = range.value && cutoff ? Math.max(0, dates.findIndex(d => d >= cutoff.toISOString().slice(0, 10))) : 0;
  const zoom = { startValue: first, endValue: Math.max(0, dates.length - 1) };
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
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], ...zoom }, { type: 'slider', xAxisIndex: [0, 1], ...zoom, bottom: 0, height: 18 }],
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
  <div class="my-3 flex flex-wrap items-center gap-2">
    <Button
      v-for="r in [{ value: 1, label: '近1月' }, { value: 3, label: '近3月' }, { value: 0, label: '全部' }]"
      :key="r.value"
      size="sm"
      :variant="range === r.value ? 'secondary' : 'ghost'"
      :aria-pressed="range === r.value"
      @click="range = r.value"
    >
      {{ r.label }}
    </Button><span class="text-xs text-muted-foreground">仅缩放原累计曲线，不重算区间收益；基准同起点。</span>
  </div>
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
