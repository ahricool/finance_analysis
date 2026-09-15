<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { LineChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import { trendFollowingApi } from '@/api/trendFollowing';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { useTheme } from '@/composables/useTheme';
import type { TrendBreadthResponse, TrendMarket } from '@/types/trendFollowing';
import { breadthOption, delta5D, percent } from './breadthCharts';
import TrendRecentTransitions from './TrendRecentTransitions.vue';

use([CanvasRenderer, LineChart, GridComponent, LegendComponent, TooltipComponent]);
const props = defineProps<{ market: TrendMarket; asOf?: string; includePreview: boolean; refreshKey: number }>();
const emit = defineEmits<{ select: [value: { code: string; tradeDate: string; preview: boolean }] }>();
const { resolvedTheme } = useTheme();
const history = shallowRef<TrendBreadthResponse | null>(null);
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(false);
let requestId = 0;
async function load() {
  const current = ++requestId;
  history.value = null;
  error.value = null;
  loading.value = true;
  try {
    const result = await trendFollowingApi.breadthHistory(props.market, props.asOf, props.includePreview);
    if (current === requestId) history.value = result;
  } catch (reason) {
    if (current === requestId) error.value = getParsedApiError(reason);
  } finally {
    if (current === requestId) loading.value = false;
  }
}
watch(() => [props.market, props.asOf, props.includePreview, props.refreshKey], () => void load(), { immediate: true });
onBeforeUnmount(() => { requestId++; });
const points = computed(() => history.value?.points ?? []);
const latest = computed(() => points.value.at(-1));
const option = computed(() => breadthOption(points.value, resolvedTheme.value === 'dark'));
const structureOption = computed(() => breadthOption(points.value, resolvedTheme.value === 'dark', true));
const metrics = [
  { key: 'trendBreadth', label: 'Trend Breadth', description: '健康趋势 TRENDING' },
  { key: 'participation', label: 'Trend Participation', description: '包含潜在趋势 CANDIDATE' },
  { key: 'deteriorationBreadth', label: 'Deterioration', description: '趋势弱化或破坏' },
] as const;
const warnings = computed(() => [
  ...(history.value?.warnings ?? []),
  ...points.value.filter(point => point.warning).map(point => `${point.tradeDate}${point.isPreview ? ' Preview' : ''}：${point.warning}`),
]);
</script>

<template>
  <div
    class="space-y-4"
    data-testid="trend-market-overview"
  >
    <section
      class="min-w-0 rounded-xl border bg-card p-4 text-card-foreground"
      data-testid="trend-breadth"
      :aria-busy="loading"
    >
      <div class="flex items-start justify-between gap-4">
        <div>
          <h3 class="font-semibold">
            趋势广度 · 最近 30 个交易日
          </h3>
          <p class="mt-1 text-xs text-muted-foreground">
            观察趋势扩散与退潮 · 基于正式 Snapshot session
          </p>
        </div>
        <span class="text-xs text-muted-foreground">{{ latest?.tradeDate }} <span
          v-if="latest?.isPreview"
          class="ml-1 rounded border border-amber-500/50 px-1.5 py-0.5 text-amber-700 dark:text-amber-400"
        >Preview</span></span>
      </div>
      <p
        v-if="loading"
        class="py-20 text-center text-sm text-muted-foreground"
      >
        正在加载趋势广度…
      </p>
      <AppApiErrorAlert
        v-else-if="error"
        class="mt-4"
        :error="error"
        action-label="重试趋势广度"
        @action="load"
        @dismiss="error = null"
      />
      <template v-else-if="points.length">
        <div class="my-5 grid grid-cols-3 divide-x rounded-lg bg-muted/40 py-4">
          <div
            v-for="metric in metrics"
            :key="metric.key"
            class="px-5"
            :data-testid="`trend-kpi-${metric.key}`"
          >
            <p class="text-xs font-medium text-muted-foreground">
              {{ metric.label }}
            </p>
            <div class="mt-2 flex items-baseline gap-3 tabular-nums">
              <strong class="text-3xl font-semibold tracking-tight">{{ percent(latest?.[metric.key]) }}</strong>
              <span
                class="text-sm"
                :class="metric.key === 'deteriorationBreadth' ? 'text-orange-700 dark:text-orange-400' : 'text-emerald-700 dark:text-emerald-400'"
              >{{ delta5D(points, metric.key) }} <span class="text-xs text-muted-foreground">/ 5D</span></span>
            </div>
            <p class="mt-1 text-xs text-muted-foreground">
              {{ metric.description }}
            </p>
          </div>
        </div>
        <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div class="min-w-0">
            <h4 class="mb-3 text-sm font-medium">
              有效趋势与恶化占比
            </h4>
            <div class="h-[280px]">
              <VChart
                :option="option"
                :update-options="{ notMerge: true }"
                autoresize
                role="img"
                aria-label="趋势广度与恶化广度折线图"
              />
            </div>
          </div>
          <div class="min-w-0">
            <h4 class="mb-3 text-sm font-medium">
              趋势状态结构 · 最近 30 个交易日
            </h4>
            <div class="h-[280px]">
              <VChart
                :option="structureOption"
                :update-options="{ notMerge: true }"
                autoresize
                role="img"
                aria-label="趋势状态结构百分比堆叠面积图"
              />
            </div>
          </div>
        </div>
        <p class="mt-3 text-xs text-muted-foreground">
          {{ history?.officialCount }} 个正式 session{{ history?.previewDate ? ' + 1 Preview（空心末尾点）' : '' }} · 5D 为相隔 5 个 session 的百分点变化，历史不足显示 — · 分母为当日可排名股票
        </p>
        <p
          v-if="latest?.coverage != null"
          class="mt-1 text-xs text-muted-foreground"
        >
          当前 State coverage {{ percent(latest.coverage) }} · {{ latest.rankableCount }} 只可排名股票
        </p>
        <details
          v-if="warnings.length"
          class="mt-3 rounded border border-amber-500/40 p-3 text-xs text-amber-800 dark:text-amber-300"
        >
          <summary class="cursor-pointer">
            数据提示 · {{ warnings.length }} 项（缺失占比不归一化）
          </summary>
          <p
            v-for="warning in warnings"
            :key="warning"
            class="mt-2"
          >
            {{ warning }}
          </p>
        </details>
      </template>
      <p
        v-else
        class="py-12 text-center text-sm text-muted-foreground"
      >
        暂无趋势广度历史
      </p>
    </section>
    <TrendRecentTransitions
      v-bind="props"
      @select="emit('select', $event)"
    />
  </div>
</template>
