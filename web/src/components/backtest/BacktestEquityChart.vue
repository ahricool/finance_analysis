<script setup lang="ts">
import type { BacktestEquity, BacktestTrade } from '@/types/backtests';
import { BarChart, LineChart, ScatterChart } from 'echarts/charts';
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { computed } from 'vue';
import VChart from 'vue-echarts';

use([CanvasRenderer, LineChart, BarChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent]);
const props = defineProps<{ equity: BacktestEquity[]; trades: BacktestTrade[] }>();
const dates = computed(() => props.equity.map((item) => item.tradingDate));
const pointByDate = computed(() => Object.fromEntries(props.equity.map((item) => [item.tradingDate, item])));
const valueAxis = { type: 'value', axisLabel: { color: '#8c98a9' }, splitLine: { lineStyle: { color: 'rgba(120,130,145,.15)' } } } as const;

function commonOption() {
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 20, top: 38, bottom: 42 },
    xAxis: {
      type: 'category',
      data: dates.value,
      axisLabel: { color: '#8c98a9' },
      axisLine: { lineStyle: { color: '#344054' } },
    },
    yAxis: valueAxis,
    dataZoom: [{ type: 'inside' }],
  };
}

const equityOption = computed(() => ({
  ...commonOption(),
  legend: { data: ['策略净值', '基准净值', '买入', '卖出'], textStyle: { color: '#8c98a9' } },
  series: [
    { name: '策略净值', type: 'line', showSymbol: false, data: props.equity.map((item) => item.totalEquity), lineStyle: { color: '#22d3ee' } },
    { name: '基准净值', type: 'line', showSymbol: false, data: props.equity.map((item) => item.benchmarkEquity), lineStyle: { color: '#a78bfa' } },
    { name: '买入', type: 'scatter', symbolSize: 10, data: props.trades.filter((item) => item.side === 'buy').map((item) => [item.tradeDate, pointByDate.value[item.tradeDate]?.totalEquity]), itemStyle: { color: '#ef4444' } },
    { name: '卖出', type: 'scatter', symbolSize: 10, data: props.trades.filter((item) => item.side === 'sell').map((item) => [item.tradeDate, pointByDate.value[item.tradeDate]?.totalEquity]), itemStyle: { color: '#22c55e' } },
  ],
}));
const drawdownOption = computed(() => ({ ...commonOption(), series: [{ type: 'line', areaStyle: { opacity: 0.2 }, data: props.equity.map((item) => item.drawdownPct), lineStyle: { color: '#f97316' } }] }));
const returnOption = computed(() => ({ ...commonOption(), series: [{ type: 'bar', data: props.equity.map((item) => ({ value: item.dailyReturnPct, itemStyle: { color: item.dailyReturnPct >= 0 ? '#ef4444' : '#22c55e' } })) }] }));
const positionOption = computed(() => ({ ...commonOption(), yAxis: { ...valueAxis, min: 0, max: 100 }, series: [{ type: 'line', areaStyle: { opacity: 0.2 }, data: props.equity.map((item) => item.totalEquity ? item.positionValue / item.totalEquity * 100 : 0), lineStyle: { color: '#38bdf8' } }] }));
</script>

<template>
  <div
    v-if="!equity.length"
    class="rounded-2xl border border-border/70 bg-card/94 p-10 text-center text-sm text-muted-text"
  >
    暂无净值数据
  </div>
  <div
    v-else
    class="grid gap-4 xl:grid-cols-2"
  >
    <section class="rounded-2xl border border-border/70 bg-card/94 p-3 xl:col-span-2">
      <h3 class="px-2 text-sm font-semibold text-foreground">
        策略净值、基准与买卖点
      </h3><VChart
        class="h-80"
        :option="equityOption"
        autoresize
      />
    </section>
    <section class="rounded-2xl border border-border/70 bg-card/94 p-3">
      <h3 class="px-2 text-sm font-semibold text-foreground">
        回撤曲线
      </h3><VChart
        class="h-64"
        :option="drawdownOption"
        autoresize
      />
    </section>
    <section class="rounded-2xl border border-border/70 bg-card/94 p-3">
      <h3 class="px-2 text-sm font-semibold text-foreground">
        每日收益
      </h3><VChart
        class="h-64"
        :option="returnOption"
        autoresize
      />
    </section>
    <section class="rounded-2xl border border-border/70 bg-card/94 p-3 xl:col-span-2">
      <h3 class="px-2 text-sm font-semibold text-foreground">
        持仓比例
      </h3><VChart
        class="h-64"
        :option="positionOption"
        autoresize
      />
    </section>
  </div>
</template>
