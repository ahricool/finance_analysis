<script setup lang="ts">
import { computed } from 'vue';
import { use } from 'echarts/core';
import type { ECElementEvent } from 'echarts/core';
import { LineChart, HeatmapChart, BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, VisualMapComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import { useTheme } from '@/composables/useTheme';
import type { History, Observation } from '@/api/marketSentiment';
import { boards } from './display';
use([LineChart, HeatmapChart, BarChart, GridComponent, TooltipComponent, VisualMapComponent, LegendComponent, CanvasRenderer]);
const props = defineProps<{ history: History; observation: Observation | null }>();
const emit = defineEmits<{ date: [value: string]; reason: [value: string] }>();
const { resolvedTheme } = useTheme();
const color = computed(() => resolvedTheme.value === 'dark' ? '#c7cbd1' : '#525866');
const base = computed(() => ({ animation: false, textStyle: { color: color.value }, tooltip: { trigger: 'axis', renderMode: 'richText', confine: true },
  legend: { textStyle: { color: color.value } }, grid: { left: 60, right: 30, top: 35, bottom: 30 },
  xAxis: { type: 'category', data: props.history.dates, axisLabel: { color: color.value, formatter: (v: string) => v.slice(5) } },
  yAxis: { type: 'value', axisLabel: { color: color.value }, minInterval: 1 },
}));
const counts = computed(() => ({ ...base.value, series: [
  { name: '涨停数', key: 'limitUpCount', color: '#e5484d' }, { name: '首板', key: 'firstBoardCount', color: '#d99832' }, { name: '连板', key: 'multiBoardCount', color: '#4c8fdb' },
].map(s => ({ type: 'line', name: s.name, connectNulls: false, itemStyle: { color: s.color }, data: props.history.items.map(r => r?.[s.key as 'limitUpCount'] ?? null) })) }));
const heat = computed(() => ({ ...base.value, yAxis: { type: 'value', min: 0, max: 100, axisLabel: { color: color.value } }, series: [{ type: 'line', name: '热度分数', connectNulls: false, itemStyle: { color: '#be6ba6' }, data: props.history.items.map(r => r?.heatScore ?? null) }] }));
const matrix = computed(() => ({ ...base.value, tooltip: { renderMode: 'richText', confine: true },
  grid: { left: 60, right: 30, top: 10, bottom: 60 },
  yAxis: { type: 'category', data: boards.map(b => `${b}板`), axisLabel: { color: color.value } },
  visualMap: { min: 0, max: Math.max(1, ...props.history.items.flatMap(r => Object.values(r?.boardDistribution ?? {}).filter((n): n is number => n != null))), orient: 'horizontal', bottom: 0, left: 'center', textStyle: { color: color.value }, inRange: { color: ['#dfe8ed', '#e5484d'] } },
  series: [{ type: 'heatmap', data: props.history.items.flatMap((r, x) => boards.flatMap((b, y) => r?.boardDistribution[b] == null ? [] : [[x, y, r.boardDistribution[b]]])), label: { show: true }, itemStyle: { borderColor: resolvedTheme.value === 'dark' ? '#171717' : '#fff', borderWidth: 1 } }],
}));
const reasons = computed(() => ({ ...base.value, tooltip: { renderMode: 'richText', confine: true }, legend: undefined,
  grid: { left: 210, right: 35, top: 10, bottom: 25 }, xAxis: { type: 'value', minInterval: 1, axisLabel: { color: color.value } },
  yAxis: { type: 'category', inverse: true, data: props.observation?.reasons.slice(0, 12).map(r => r.reason) ?? [], axisLabel: { color: color.value, width: 190, overflow: 'truncate' } },
  series: [{ type: 'bar', itemStyle: { color: '#4c8fdb' }, data: props.observation?.reasons.slice(0, 12).map(r => r.count) ?? [] }],
}));
function selectDate(e: ECElementEvent) {
  const index = Array.isArray(e.value) ? Number(e.value[0]) : e.dataIndex;
  const value = props.history.dates[index]; if (value) emit('date', value);
}
</script>
<template>
  <section class="space-y-3 rounded-xl border p-4">
    <h2 class="text-lg font-semibold">
      近30个交易日 · 完整池联动
    </h2>
    <p class="text-xs text-muted-foreground">
      家数、板位与热度分轨展示；空白表示缺失。点击图中日期联动所选日。
    </p>
    <div
      class="h-64"
      aria-label="涨停参与度历史"
    >
      <VChart
        :option="counts"
        autoresize
        @click="selectDate"
      />
    </div>
    <div
      class="h-72"
      aria-label="完整涨停池板位矩阵"
    >
      <VChart
        :option="matrix"
        autoresize
        @click="selectDate"
      />
    </div>
    <div
      class="h-48"
      aria-label="热度历史"
    >
      <VChart
        :option="heat"
        autoresize
        @click="selectDate"
      />
    </div>
    <div class="flex flex-wrap gap-1">
      <button
        v-for="day in history.dates"
        :key="day"
        class="rounded border px-2 py-1 text-xs hover:bg-muted"
        @click="emit('date', day)"
      >
        {{ day.slice(5) }}
      </button>
    </div>
  </section>
  <section class="space-y-3 rounded-xl border p-4">
    <h2 class="text-lg font-semibold">
      涨停原因分布
    </h2>
    <p class="text-xs text-muted-foreground">
      主观察口径，按完整原因文本聚合；展示前12项，点击筛选明细。未提供原因独立计数。
    </p>
    <div
      v-if="observation?.reasons.length"
      class="h-80"
    >
      <VChart
        :option="reasons"
        autoresize
        @click="e => emit('reason', e.name)"
      />
    </div>
    <p
      v-else
      class="text-sm text-muted-foreground"
    >
      暂无可用原因分布
    </p>
  </section>
</template>
