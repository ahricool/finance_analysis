<script setup lang="ts">
import type { ETFMomentumSnapshot } from '@/types/etfRotation';
import { LineChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { computed } from 'vue';
import VChart from 'vue-echarts';

use([CanvasRenderer, LineChart, GridComponent, LegendComponent, TooltipComponent]);
const props = defineProps<{ history: ETFMomentumSnapshot[] }>();
const ordered = computed(() => [...props.history].reverse());
function option(series: Array<{ name: string; values: Array<number | null> }>, inverse = false) {
  return {
    animation: false,
    tooltip: { trigger: 'axis' }, legend: { top: 0, textStyle: { fontSize: 10 } },
    grid: { left: 46, right: 16, top: 34, bottom: 28 },
    xAxis: { type: 'category', data: ordered.value.map(row => row.tradeDate), axisLabel: { fontSize: 9 } },
    yAxis: { type: 'value', inverse, scale: true, axisLabel: { fontSize: 9 } },
    series: series.map(item => ({ name: item.name, type: 'line', showSymbol: false, connectNulls: false, data: item.values })),
  };
}
const priceOption = computed(() => option([
  { name: 'Price', values: ordered.value.map(row => row.referencePrice) },
  { name: 'MA10', values: ordered.value.map(row => row.referencePrice === null || row.ma10Ratio === null ? null : row.referencePrice / (1 + row.ma10Ratio)) },
  { name: 'MA20', values: ordered.value.map(row => row.referencePrice === null ? null : row.referencePrice / (1 + row.ma20Ratio)) },
]));
const compositeOption = computed(() => option([{ name: 'Composite', values: ordered.value.map(row => row.compositeScore) }]));
const rankOption = computed(() => option([{ name: 'Rank', values: ordered.value.map(row => row.rank) }], true));
const rsOption = computed(() => option([
  { name: 'RS5', values: ordered.value.map(row => row.rs5D) },
  { name: 'RS10', values: ordered.value.map(row => row.rs10D) },
  { name: 'RS20', values: ordered.value.map(row => row.rs20D) },
]));
</script>

<template>
  <div
    class="grid min-w-0 gap-3 lg:grid-cols-2"
    data-testid="rotation-history-charts"
  >
    <div
      v-for="chart in [
        { label: '价格与均线', option: priceOption },
        { label: '综合得分', option: compositeOption },
        { label: '排名', option: rankOption },
        { label: '相对强度', option: rsOption },
      ]"
      :key="chart.label"
      class="h-56 min-w-0 rounded border"
    >
      <VChart
        :option="chart.option"
        autoresize
        role="img"
        :aria-label="chart.label"
      />
    </div>
  </div>
</template>
