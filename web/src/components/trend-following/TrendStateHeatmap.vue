<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { HeatmapChart, type HeatmapSeriesOption } from 'echarts/charts';
import { DataZoomComponent, GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components';
import type { DataZoomComponentOption, GridComponentOption, TooltipComponentOption, VisualMapComponentOption } from 'echarts/components';
import { use, type ComposeOption } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import { trendFollowingApi } from '@/api/trendFollowing';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import { useTheme } from '@/composables/useTheme';
import { formatFullDateTimeWithTimezone } from '@/utils/format';
import type { TrendMarket, TrendStateHistoryResponse } from '@/types/trendFollowing';
import { HEATMAP_STATES, STATE_COLORS, stateTooltip } from './stateHeatmap';

use([CanvasRenderer, HeatmapChart, DataZoomComponent, GridComponent, TooltipComponent, VisualMapComponent]);
const props = defineProps<{ market: TrendMarket; asOf?: string; includePreview: boolean; refreshKey: number }>();
const emit = defineEmits<{ select: [value: { code: string; tradeDate: string; preview: boolean }] }>();
const { resolvedTheme } = useTheme();
const history = shallowRef<TrendStateHistoryResponse | null>(null);
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(false);
const chart = ref<InstanceType<typeof VChart> | null>(null);
let requestId = 0;
async function load() {
  const current = ++requestId;
  history.value = null;
  error.value = null;
  loading.value = true;
  try {
    const result = await trendFollowingApi.stateHistory(props.market, props.asOf, props.includePreview);
    if (current === requestId) history.value = result;
  } catch (reason) {
    if (current === requestId) error.value = getParsedApiError(reason);
  } finally {
    if (current === requestId) loading.value = false;
  }
}
watch(() => [props.market, props.asOf, props.includePreview, props.refreshKey], () => void load(), { immediate: true });
onBeforeUnmount(() => { requestId++; });

type ChartEvent = { componentType?: string; dataIndex?: number; value?: unknown };
function rowIndex(event: ChartEvent) {
  if (event.componentType === 'yAxis') return history.value?.items.findIndex(item => item.code === event.value) ?? -1;
  return event.componentType === 'series' && event.dataIndex != null
    ? Math.floor(event.dataIndex / (history.value?.dates.length || 1)) : -1;
}
function clearHighlight() { chart.value?.dispatchAction({ type: 'downplay', seriesIndex: 0 }); }
function highlight(event: ChartEvent) {
  clearHighlight();
  const y = rowIndex(event);
  const count = history.value?.dates.length ?? 0;
  if (y >= 0) chart.value?.dispatchAction({ type: 'highlight', seriesIndex: 0,
    dataIndex: Array.from({ length: count }, (_, x) => y * count + x) });
}
function select(event: ChartEvent) {
  const stock = history.value?.items[rowIndex(event)];
  if (stock && history.value?.anchorDate) emit('select', {
    code: stock.code, tradeDate: history.value.anchorDate, preview: history.value.previewDate != null,
  });
}
const option = computed<ComposeOption<HeatmapSeriesOption | DataZoomComponentOption | GridComponentOption | TooltipComponentOption | VisualMapComponentOption>>(() => {
  const data = history.value;
  const byCode = new Map(data?.items.map(stock => [stock.code, stock]));
  const dark = resolvedTheme.value === 'dark';
  const muted = dark ? '#d4d4d4' : '#404040';
  const border = dark ? '#171717' : '#ffffff';
  return {
    animation: false,
    grid: { left: 210, right: 42, top: 44, bottom: 20 },
    tooltip: {
      trigger: 'item', confine: true, renderMode: 'richText',
      backgroundColor: dark ? '#262626' : '#ffffff', borderColor: dark ? '#525252' : '#d4d4d4',
      textStyle: { color: dark ? '#fafafa' : '#171717', fontSize: 12 },
      formatter: params => {
        const point = Array.isArray(params) ? params[0] : params;
        if (!point || !data) return '';
        const x = point.dataIndex % data.dates.length;
        const y = Math.floor(point.dataIndex / data.dates.length);
        return stateTooltip(data, x, y);
      },
    },
    xAxis: {
      type: 'category', position: 'top', data: data?.dates ?? [],
      axisLabel: { color: muted, fontSize: 10, hideOverlap: true, showMaxLabel: true,
        formatter: (day: string) => `${day.slice(5).replace('-', '/')}${day === data?.previewDate ? ' P' : ''}` },
      axisLine: { show: false }, axisTick: { show: false }, splitArea: { show: false },
    },
    yAxis: {
      type: 'category', inverse: true, triggerEvent: true, data: data?.items.map(item => item.code) ?? [],
      axisLabel: { color: muted, fontSize: 11, width: 190, overflow: 'truncate', interval: 0,
        formatter: (code: string) => {
          const stock = byCode.get(code);
          return stock ? `#${stock.currentRank} ${stock.code} ${stock.name}` : '';
        } },
      axisLine: { show: false }, axisTick: { show: false },
    },
    dataZoom: [
      { type: 'slider', yAxisIndex: 0, right: 2, width: 18, top: 44, bottom: 20,
        startValue: 0, endValue: 19, zoomLock: true, showDetail: false, brushSelect: false,
        borderColor: dark ? '#525252' : '#d4d4d4' },
      // ECharts zoomLock disables wheel listeners; equal spans keep row sizing fixed without it.
      { type: 'inside', yAxisIndex: 0, startValue: 0, endValue: 19,
        minValueSpan: Math.min(19, (data?.items.length || 1) - 1),
        maxValueSpan: Math.min(19, (data?.items.length || 1) - 1),
        zoomOnMouseWheel: false, moveOnMouseWheel: true, moveOnMouseMove: true },
    ],
    visualMap: {
      type: 'piecewise', show: false, dimension: 2,
      pieces: [
        { value: -1, color: dark ? '#303036' : '#f4f4f5' },
        ...HEATMAP_STATES.map((state, value) => ({ value, color: STATE_COLORS[state][resolvedTheme.value] })),
      ],
    },
    series: [{
      type: 'heatmap', name: 'Trend State', progressive: 0,
      itemStyle: { borderColor: border, borderWidth: 1 },
      emphasis: { itemStyle: { borderColor: dark ? '#fafafa' : '#262626', borderWidth: 2 } },
      data: data?.items.flatMap((stock, y) => data.dates.map((day, x) => ({
        value: [x, y, stock.history[x] ? HEATMAP_STATES.indexOf(stock.history[x]!.state) : -1],
        ...(day === data.previewDate ? { itemStyle: { borderColor: dark ? '#e5e7eb' : '#475569', borderWidth: 2 } } : {}),
      }))) ?? [],
    }],
  };
});
</script>

<template>
  <section
    class="min-w-0 rounded-xl border bg-card p-4 text-card-foreground"
    data-testid="trend-state-heatmap"
    :aria-busy="loading"
  >
    <h3 class="font-semibold">
      趋势状态轨迹
    </h3>
    <p class="mt-1 text-xs text-muted-foreground">
      最近 30 个交易日 · 当前 Top 50{{ history?.anchorDate ? ` · 锚点 ${history.anchorDate}` : '' }}
      · 按锚点 Rank 固定股票集合 · 滚动查看全部股票，点击查看详情
    </p>
    <div
      class="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs"
      aria-label="趋势状态图例"
    >
      <span
        v-for="state in HEATMAP_STATES"
        :key="state"
        class="inline-flex items-center gap-1.5"
      >
        <span
          class="inline-block size-3 rounded-sm"
          :style="{ backgroundColor: STATE_COLORS[state][resolvedTheme] }"
        />{{ state }}
      </span>
      <span class="inline-flex items-center gap-1.5"><span class="inline-block size-3 rounded-sm border bg-zinc-100 dark:bg-zinc-800" />缺失</span>
    </div>
    <p
      v-if="loading"
      class="py-20 text-center text-sm text-muted-foreground"
    >
      正在加载状态历史…
    </p>
    <div
      v-else-if="error"
      class="mt-4 space-y-2"
    >
      <p class="text-sm">
        状态历史加载失败
      </p>
      <AppApiErrorAlert :error="error" />
      <Button
        variant="outline"
        size="sm"
        @click="load"
      >
        重试状态历史
      </Button>
    </div>
    <template v-else>
      <p
        v-if="history?.previewDate"
        class="mt-3 text-sm text-amber-700 dark:text-amber-400"
      >
        {{ history.previewDate }} Preview · P 列为当天预演，边框标识，不计入 30 个正式交易日。
        {{ formatFullDateTimeWithTimezone(history.previewTime) }}
      </p>
      <div
        v-if="history?.items.length"
        class="mt-2 h-[600px] min-w-0"
      >
        <VChart
          ref="chart"
          :option="option"
          :update-options="{ notMerge: true }"
          autoresize
          role="img"
          aria-label="趋势状态热力图，横轴为交易日，纵轴按锚点排名排列，滚轮查看全部股票，点击股票打开详情"
          @mouseover="highlight"
          @mouseout="clearHighlight"
          @click="select"
        />
      </div>
      <p
        v-else
        class="py-20 text-center text-sm text-muted-foreground"
      >
        暂无状态历史
      </p>
      <p
        v-if="history"
        class="mt-2 text-xs text-muted-foreground"
      >
        {{ history.items.length }} 只股票 · {{ history.officialCount }} 个正式 Snapshot 交易日 · 缺失不补值
        <span v-if="history.generatedAt"> · 正式数据更新：{{ formatFullDateTimeWithTimezone(history.generatedAt) }}</span>
      </p>
      <p
        v-for="warning in history?.warnings"
        :key="warning"
        class="mt-2 text-xs text-muted-foreground"
      >
        {{ warning }}
      </p>
    </template>
  </section>
</template>
