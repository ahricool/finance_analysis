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
  <div class="grid gap-3 lg:grid-cols-2">
    <VChart
      class="h-56 min-w-0 rounded border"
      :option="priceOption"
      autoresize
    />
    <VChart
      class="h-56 min-w-0 rounded border"
      :option="compositeOption"
      autoresize
    />
    <VChart
      class="h-56 min-w-0 rounded border"
      :option="rankOption"
      autoresize
    />
    <VChart
      class="h-56 min-w-0 rounded border"
      :option="rsOption"
      autoresize
    />
  </div>
</template>
