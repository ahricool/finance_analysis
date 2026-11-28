<script setup lang="ts">
import { getDisplayTimezone, formatFullDateTimeWithTimezone, displayTimezoneLabel } from '@/utils/format';
import { computed } from 'vue';
import { ChartNoAxesCombined } from 'lucide-vue-next';
import VChart from 'vue-echarts';
import { graphic, use } from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { useTheme } from '@/composables/useTheme';

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);
const props = defineProps<{ points: { time: string; equity: string | null }[]; unit: string }>();
const { resolvedTheme } = useTheme();
const amount = new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const samples = computed(() => props.points.map(({ time, equity }): [number, number | null] => {
  const value = equity?.trim() ? Number(equity) : NaN;
  return [Date.parse(time), Number.isFinite(value) ? value : null];
}).filter(([time]) => Number.isFinite(time)).sort((a, b) => a[0] - b[0]));
const latest = computed(() => samples.value.filter((p): p is [number, number] => p[1] !== null).at(-1));
const options = computed(() => {
  const formatter = new Intl.DateTimeFormat('zh-CN', {
    timeZone: getDisplayTimezone(), month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  });
  const axisPointer = { label: { formatter: ({ value }: { value: number }) => formatter.format(value) } };
  const dark = resolvedTheme.value === 'dark';
  const ink = dark ? '#abb7c6' : '#566579';
  const line = dark ? '#80b4ff' : '#356cc1';
  return {
    animation: false, useUTC: true,
    grid: { containLabel: true, left: 4, right: 14, top: 12, bottom: 6 },
    tooltip: {
      trigger: 'axis', confine: true, backgroundColor: dark ? '#202936' : '#fff',
      textStyle: { color: ink }, axisPointer: { type: 'line', lineStyle: { color: line, type: 'dashed' } },
      valueFormatter: (value: unknown) => typeof value === 'number' ? amount.format(value) + ' ' + props.unit : '—',
    },
    xAxis: { type: 'time', axisPointer, splitNumber: 4, axisTick: { show: false }, axisLine: { show: false },
      axisLabel: { color: ink, fontSize: 10, hideOverlap: true, formatter: (value: number) => formatter.format(value) } },
    yAxis: { type: 'value', scale: true, splitNumber: 4, axisLabel: { color: ink, fontSize: 10 },
      splitLine: { lineStyle: { type: 'dashed', color: dark ? '#333d4b' : '#dce2eb' } } },
    series: [{ name: '账户权益', type: 'line', data: samples.value, showSymbol: true,
      symbol: 'circle', symbolSize: (_value: unknown, params: { dataIndex: number }) => {
        const i = params.dataIndex;
        return samples.value[i + 1]?.[1] == null || samples.value[i - 1]?.[1] == null ? 5 : 0;
      },
      lineStyle: { width: 2 }, itemStyle: { color: line },
      areaStyle: { color: new graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: dark ? 'rgba(128,180,255,.23)' : 'rgba(53,108,193,.17)' },
        { offset: 1, color: 'rgba(80,140,220,0)' },
      ]) },
    }],
  };
});
</script>

<template>
  <figure class="min-w-0 rounded-xl border bg-card p-5">
    <figcaption class="flex flex-wrap items-baseline justify-between gap-2">
      <h2 class="text-base font-semibold">
        账户权益曲线
      </h2>
      <span class="text-xs text-muted-foreground">{{ unit }} · {{ displayTimezoneLabel() }}</span>
    </figcaption>
    <template v-if="latest">
      <div class="mt-2 flex flex-wrap items-baseline gap-x-3">
        <strong class="text-2xl font-semibold tracking-tight tabular-nums">{{ amount.format(latest[1]) }}</strong>
        <time
          class="text-xs text-muted-foreground"
          :datetime="new Date(latest[0]).toISOString()"
        >
          {{ formatFullDateTimeWithTimezone(latest[0]) }}
        </time>
      </div>
      <div class="mt-2 h-44 w-full sm:h-52">
        <VChart
          :option="options"
          autoresize
        />
      </div>
    </template>
    <div
      v-else
      class="mt-4 flex min-h-44 flex-col items-center justify-center gap-2 rounded-lg bg-muted/40 text-sm text-muted-foreground"
    >
      <ChartNoAxesCombined
        class="size-6"
        aria-hidden="true"
      />
      等待账户权益记录
    </div>
  </figure>
</template>
