<script setup lang="ts">
import type { BacktestEquity, BacktestTrade } from '@/types/backtests';
import { BarChart, LineChart, ScatterChart } from 'echarts/charts';
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { computed } from 'vue';
import VChart from 'vue-echarts';
import { useMediaQuery } from '@vueuse/core';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useTheme } from '@/composables/useTheme';

use([
  CanvasRenderer,
  LineChart,
  BarChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
]);
const props = defineProps<{ equity: BacktestEquity[]; trades: BacktestTrade[] }>();
const { resolvedTheme } = useTheme();
const isMobile = useMediaQuery('(max-width: 639px)');
const dates = computed(() => props.equity.map((item) => item.tradingDate));
const pointByDate = computed(() =>
  Object.fromEntries(props.equity.map((item) => [item.tradingDate, item])),
);

function commonOption() {
  const muted = resolvedTheme.value === 'dark' ? '#a9afbd' : '#667085';
  const gridLine = resolvedTheme.value === 'dark' ? 'rgba(255,255,255,.1)' : 'rgba(15,23,42,.09)';
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: isMobile.value ? 42 : 54, right: 12, top: isMobile.value ? 54 : 42, bottom: 42 },
    xAxis: {
      type: 'category',
      data: dates.value,
      axisLabel: { color: muted, hideOverlap: true, fontSize: isMobile.value ? 10 : 12 },
      axisLine: { lineStyle: { color: gridLine } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: muted, fontSize: isMobile.value ? 10 : 12 },
      splitLine: { lineStyle: { color: gridLine } },
    },
    dataZoom: [{ type: 'inside' }],
  };
}

const equityOption = computed(() => ({
  ...commonOption(),
  legend: {
    data: ['策略净值', '基准净值', '买入', '卖出'],
    type: 'scroll',
    textStyle: { color: resolvedTheme.value === 'dark' ? '#d5d8e0' : '#475467' },
  },
  series: [
    {
      name: '策略净值',
      type: 'line',
      showSymbol: false,
      data: props.equity.map((item) => item.totalEquity),
      lineStyle: { color: '#df7997' },
    },
    {
      name: '基准净值',
      type: 'line',
      showSymbol: false,
      data: props.equity.map((item) => item.benchmarkEquity),
      lineStyle: { color: '#4f9ccc' },
    },
    {
      name: '买入',
      type: 'scatter',
      symbolSize: 10,
      data: props.trades
        .filter((item) => item.side === 'buy')
        .map((item) => [item.tradeDate, pointByDate.value[item.tradeDate]?.totalEquity]),
      itemStyle: { color: '#ef4444' },
    },
    {
      name: '卖出',
      type: 'scatter',
      symbolSize: 10,
      data: props.trades
        .filter((item) => item.side === 'sell')
        .map((item) => [item.tradeDate, pointByDate.value[item.tradeDate]?.totalEquity]),
      itemStyle: { color: '#22c55e' },
    },
  ],
}));
const drawdownOption = computed(() => ({
  ...commonOption(),
  series: [
    {
      type: 'line',
      areaStyle: { opacity: 0.2 },
      data: props.equity.map((item) => item.drawdownPct),
      lineStyle: { color: '#f97316' },
    },
  ],
}));
const returnOption = computed(() => ({
  ...commonOption(),
  series: [
    {
      type: 'bar',
      data: props.equity.map((item) => ({
        value: item.dailyReturnPct,
        itemStyle: { color: item.dailyReturnPct >= 0 ? '#ef4444' : '#22c55e' },
      })),
    },
  ],
}));
const positionOption = computed(() => ({
  ...commonOption(),
  yAxis: { ...(commonOption().yAxis as object), min: 0, max: 100 },
  series: [
    {
      type: 'line',
      areaStyle: { opacity: 0.2 },
      data: props.equity.map((item) =>
        item.totalEquity ? (item.positionValue / item.totalEquity) * 100 : 0,
      ),
      lineStyle: { color: '#4f9ccc' },
    },
  ],
}));
</script>

<template>
  <div
    v-if="!equity.length"
    class="rounded-xl border bg-card p-10 text-center text-sm text-muted-foreground"
  >
    暂无净值数据
  </div>
  <div
    v-else
    class="grid gap-4 xl:grid-cols-2"
  >
    <Card class="min-w-0 xl:col-span-2">
      <CardHeader><CardTitle>策略净值、基准与买卖点</CardTitle><CardDescription>对比策略和基准表现，并标注交易事件。</CardDescription></CardHeader>
      <CardContent>
        <VChart
          class="h-80"
          :option="equityOption"
          autoresize
        />
      </CardContent>
    </Card>
    <Card class="min-w-0">
      <CardHeader><CardTitle>回撤曲线</CardTitle></CardHeader>
      <CardContent>
        <VChart
          class="h-64"
          :option="drawdownOption"
          autoresize
        />
      </CardContent>
    </Card>
    <Card class="min-w-0">
      <CardHeader><CardTitle>每日收益</CardTitle></CardHeader>
      <CardContent>
        <VChart
          class="h-64"
          :option="returnOption"
          autoresize
        />
      </CardContent>
    </Card>
    <Card class="min-w-0 xl:col-span-2">
      <CardHeader><CardTitle>持仓比例</CardTitle></CardHeader>
      <CardContent>
        <VChart
          class="h-64"
          :option="positionOption"
          autoresize
        />
      </CardContent>
    </Card>
  </div>
</template>
