<script setup lang="ts">
import { computed } from 'vue';
import VChart from 'vue-echarts';
import { use } from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);
const props = defineProps<{ points: { time: string; equity: string | null }[] }>();
const data = computed(() => props.points.filter(p => Number.isFinite(Date.parse(p.time))).map(p =>
  [Date.parse(p.time), p.equity == null || !Number.isFinite(Number(p.equity)) ? null : Number(p.equity)]));
const options = computed(() => ({
  animation: false, useUTC: true, tooltip: { trigger: 'axis', valueFormatter: (v: number) => v?.toFixed(2) + ' USDT' },
  grid: { containLabel: true, left: 12, right: 18, top: 25, bottom: 8 },
  xAxis: { type: 'time' }, yAxis: { type: 'value', scale: true },
  series: [{ name: '权益', type: 'line', data: data.value, showSymbol: data.value.length < 2 }],
}));
</script>

<template>
  <div>
    <h3 class="text-sm font-medium">
      账户权益曲线 · USDT
    </h3>
    <VChart
      v-if="data.some(point => point[1] != null)"
      class="h-48 w-full"
      :option="options"
      autoresize
    />
    <p
      v-else
      class="text-sm text-muted-foreground"
    >
      等待账户权益记录
    </p>
  </div>
</template>
