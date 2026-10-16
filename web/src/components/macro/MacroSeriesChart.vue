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
import { alignMacroSeries } from './chartData';
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
const selectedSeries = ref<Record<string, boolean>>({});
const hoveredKey = ref<string | null>(null);
const hoveredSeries = computed(() => props.result?.series.find(series => series.key === hoveredKey.value));
const aligned = computed(() => alignMacroSeries(props.result));
const colors = computed(() => resolvedTheme.value === 'dark'
  ? ['#60a5fa', '#c084fc', '#2dd4bf', '#fbbf24', '#fb923c', '#f472b6', '#a3e635', '#94a3b8', '#38bdf8', '#e879f9', '#fda4af', '#d4d4a5', '#a78bfa']
  : ['#2563eb', '#9333ea', '#0d9488', '#a16207', '#ea580c', '#db2777', '#4d7c0f', '#64748b', '#0284c7', '#c026d3', '#be123c', '#78716c', '#7c3aed']);
function toggleSeries(key: string) {
  selectedSeries.value = { ...selectedSeries.value, [key]: selectedSeries.value[key] === false };
  hoveredKey.value = null;
}
function showSeries(event: { componentType?: string; seriesName?: string }) {
  hoveredKey.value = event.componentType === 'series' ? event.seriesName ?? null : null;
}
watch(() => props.result, () => { hoveredKey.value = null; });
const hasPoints = computed(() => props.result?.series.some(s => s.points.length));
const option = computed<ComposeOption<LineSeriesOption | GridComponentOption | LegendComponentOption | TooltipComponentOption>>(() => {
  const result = props.result;
  return {
    animation: false, color: colors.value,
    legend: { show: false, data: result?.series.map(series => series.key), selected: selectedSeries.value },
    grid: { left: 12, right: 20, top: 16, bottom: 12, containLabel: true },
    tooltip: {
      trigger: 'item', confine: true, renderMode: 'richText', backgroundColor: palette.value.background,
      borderColor: palette.value.border, textStyle: { color: palette.value.foreground },
      formatter: (params) => {
        const point = Array.isArray(params) ? params[0] : params;
        if (!point) return '';
        const series = aligned.value.series.find(series => series.key === point.seriesName);
        const value = series?.values[point.dataIndex];
        if (!series || value == null) return '';
        const change = value - 100;
        const relative = result?.mode === 'price' ? '' : ` · 相对区间起点 ${change >= 0 ? '+' : ''}${change.toFixed(1)}%`;
        return `${aligned.value.dates[point.dataIndex]}\n${series.code ?? seriesLabel(series.key)} · ${series.name}\n${value.toFixed(result?.mode === 'price' ? 3 : 1)}${relative}${ratioDescriptions[series.key] ? `\n${ratioDescriptions[series.key]}` : ''}`;
      },
    },
    xAxis: { type: 'category', data: aligned.value.dates, axisLabel: { color: palette.value.muted, hideOverlap: true }, axisLine: { lineStyle: { color: palette.value.border } }, axisTick: { show: false }, splitLine: { show: false } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: palette.value.muted }, splitLine: { lineStyle: { color: palette.value.border } } },
    series: aligned.value.series.flatMap((series, index): LineSeriesOption[] => {
      const color = colors.value[index % colors.value.length];
      return [
        // Draw a dashed connector beneath the solid line. Only interior gaps are
        // exposed; values remain null and no leading/trailing prices are invented.
        ...(series.hasGap ? [{
          id: `${series.key}:gaps`, name: series.key, type: 'line' as const,
          data: series.values, connectNulls: true, showSymbol: false, silent: true,
          lineStyle: { color, width: 1.5, type: 'dashed' as const },
          itemStyle: { color }, tooltip: { show: false }, z: 1,
          emphasis: { disabled: true },
        }] : []),
        {
          id: series.key, name: series.key, type: 'line', data: series.values,
          connectNulls: false, smooth: false, triggerLineEvent: true,
          showSymbol: true, symbol: 'circle', symbolSize: 3,
          lineStyle: { color, width: 1.5 }, itemStyle: { color }, z: 2,
          emphasis: { focus: 'series', lineStyle: { width: 3 } },
        },
      ];
    }),
  };
});
</script>
<template>
  <div class="min-w-0 space-y-4">
    <ul
      v-if="result"
      class="flex flex-wrap gap-x-4 gap-y-2"
      :aria-label="`${label}图例`"
      data-testid="macro-legend"
    >
      <li
        v-for="(series, index) in result.series"
        :key="series.key"
        class="max-w-full"
      >
        <button
          type="button"
          class="flex max-w-full items-center gap-1.5 rounded-sm py-0.5 text-left text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :class="{ 'opacity-40': selectedSeries[series.key] === false }"
          :aria-pressed="selectedSeries[series.key] !== false"
          :data-testid="`macro-legend-${series.key}`"
          @click="toggleSeries(series.key)"
        >
          <span
            class="relative h-0.5 w-5 shrink-0"
            :style="{ backgroundColor: colors[index % colors.length] }"
            aria-hidden="true"
          >
            <span
              class="absolute left-1/2 top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full"
              :style="{ backgroundColor: colors[index % colors.length] }"
            />
          </span>
          <span class="min-w-0 break-words"><span class="font-medium">{{ series.code ?? seriesLabel(series.key) }}</span> · {{ series.name }}</span>
        </button>
      </li>
    </ul>
    <div
      class="relative h-[30rem] min-w-0"
      :aria-busy="loading"
    >
      <Skeleton
        v-if="loading && !result"
        class="h-full w-full"
      />
      <VChart
        v-else-if="hasPoints"
        :option="option"
        :update-options="{ notMerge: true }"
        autoresize
        role="img"
        :aria-label="label"
        @mouseover="showSeries"
        @mouseout="hoveredKey = null"
        @globalout="hoveredKey = null"
      />
      <Empty
        v-else
        class="h-full"
      >
        <EmptyHeader><EmptyTitle>暂无走势数据</EmptyTitle><EmptyDescription>所选资产或区间暂无有效数据。</EmptyDescription></EmptyHeader>
      </Empty>
      <div
        v-if="hoveredSeries"
        class="pointer-events-none absolute bottom-12 right-4 max-w-[80%] rounded-md border bg-popover px-3 py-2 text-sm text-popover-foreground shadow-md"
        role="status"
      >
        {{ hoveredSeries.code ?? seriesLabel(hoveredSeries.key) }} · {{ hoveredSeries.name }}
      </div>
      <div
        v-if="loading && result"
        class="absolute inset-0 flex items-center justify-center rounded-md bg-background/70 text-sm"
        role="status"
      >
        加载中…
      </div>
    </div>
  </div>
</template>
