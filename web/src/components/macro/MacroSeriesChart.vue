<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { use, type ComposeOption } from 'echarts/core';
import { LineChart, type LineSeriesOption } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent, type GridComponentOption, type LegendComponentOption, type TooltipComponentOption } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import type { MacroSeriesResult } from '@/api/macro';
import { useTheme } from '@/composables/useTheme';
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { ratioDescriptions, seriesLabel } from './display';
use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);
const props = defineProps<{ result: MacroSeriesResult | null; loading: boolean; label: string }>();
const { resolvedTheme } = useTheme();
const palette = ref({ foreground: 'hsl(0, 0%, 20%)', muted: 'hsl(0, 0%, 45%)', border: 'hsl(0, 0%, 85%)', background: 'hsl(0, 0%, 98%)' });
watch(resolvedTheme, async () => {
  await nextTick();
  const css = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) => {
    const raw = css.getPropertyValue(name).trim();
    return raw ? `hsl(${raw.split(/\s+/).join(', ')})` : fallback;
  };
  palette.value = {
    foreground: token('--foreground', palette.value.foreground), muted: token('--muted-foreground', palette.value.muted),
    border: token('--border', palette.value.border), background: token('--popover', palette.value.background),
  };
}, { immediate: true, flush: 'post' });
const hasPoints = computed(() => props.result?.series.some(s => s.points.length));
const option = computed<ComposeOption<LineSeriesOption | GridComponentOption | LegendComponentOption | TooltipComponentOption>>(() => {
  const result = props.result;
  const colors = resolvedTheme.value === 'dark'
    ? ['#60a5fa', '#c084fc', '#2dd4bf', '#fbbf24', '#fb923c', '#f472b6', '#a3e635', '#94a3b8']
    : ['#2563eb', '#9333ea', '#0d9488', '#a16207', '#ea580c', '#db2777', '#4d7c0f', '#64748b'];
  return {
    animation: false, color: colors,
    legend: { type: 'scroll', top: 0, textStyle: { color: palette.value.muted }, formatter: (key: string) => `${seriesLabel(key)}${result?.series.find(s => s.key === key)?.partial ? ' · 数据不完整' : ''}` },
    grid: { left: 12, right: 20, top: 42, bottom: 12, containLabel: true },
    tooltip: {
      trigger: 'axis', confine: true, renderMode: 'richText', backgroundColor: palette.value.background,
      borderColor: palette.value.border, textStyle: { color: palette.value.foreground },
      formatter: (params) => {
        const entries = Array.isArray(params) ? params : [params];
        return entries.map((entry, index) => {
          const point = entry.value as [string, number];
          const key = String(entry.seriesName);
          const series = result?.series.find(s => s.key === key);
          const change = point[1] - 100;
          const relative = result?.mode === 'price' ? '' : ` · 相对区间起点 ${change >= 0 ? '+' : ''}${change.toFixed(1)}%`;
          return `${index === 0 ? `${point[0]}\n` : ''}${seriesLabel(key)}  ${point[1].toFixed(result?.mode === 'price' ? 3 : 1)}${relative}${series?.partial ? ' · 数据不完整' : ''}${ratioDescriptions[key] ? `\n${ratioDescriptions[key]}` : ''}`;
        }).join('\n');
      },
    },
    xAxis: { type: 'time', axisLabel: { color: palette.value.muted, hideOverlap: true }, axisLine: { lineStyle: { color: palette.value.border } }, axisTick: { show: false }, splitLine: { show: false } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: palette.value.muted }, splitLine: { lineStyle: { color: palette.value.border } } },
    series: result?.series.map(s => ({ name: s.key, type: 'line', showSymbol: s.points.length === 1, symbolSize: 6, smooth: false, connectNulls: false, data: s.points.map(p => [p.date, p.value]) })) ?? [],
  };
});
</script>
<template>
  <div
    class="relative h-80 min-w-0"
    :aria-busy="loading"
  >
    <Skeleton
      v-if="loading && !result"
      class="h-full w-full"
    />
    <VChart
      v-else-if="hasPoints"
      :option="option"
      :update-options="{ replaceMerge: ['series'] }"
      autoresize
      role="img"
      :aria-label="label"
    />
    <Empty
      v-else
      class="h-full"
    >
      <EmptyHeader><EmptyTitle>暂无走势数据</EmptyTitle><EmptyDescription>所选资产或区间暂无有效数据。</EmptyDescription></EmptyHeader>
    </Empty>
    <div
      v-if="loading && result"
      class="absolute inset-0 flex items-center justify-center rounded-md bg-background/70 text-sm"
      role="status"
    >
      加载中…
    </div>
  </div>
</template>
