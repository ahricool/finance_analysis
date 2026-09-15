<script setup lang="ts">
import { computed, onBeforeUnmount, shallowRef, ref, watch } from 'vue';
import { LineChart, type LineSeriesOption } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import type { GridComponentOption, LegendComponentOption, TooltipComponentOption } from 'echarts/components';
import { use, type ComposeOption } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import { etfRotationApi } from '@/api/etfRotation';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import { formatFullDateTimeWithTimezone } from '@/utils/format';
import { useTheme } from '@/composables/useTheme';
import type { ETFMarket, ETFRankHistoryResponse } from '@/types/etfRotation';

use([CanvasRenderer, LineChart, GridComponent, LegendComponent, TooltipComponent]);
const props = defineProps<{ market: ETFMarket; asOf?: string; includePreview: boolean; refreshKey: number }>();
const { resolvedTheme } = useTheme();
const history = shallowRef<ETFRankHistoryResponse | null>(null);
const loading = ref(false);
const error = shallowRef<ParsedApiError | null>(null);
let requestId = 0;
async function load() {
  const current = ++requestId;
  loading.value = true;
  error.value = null;
  history.value = null;
  try {
    const result = await etfRotationApi.rankHistory(props.market, props.asOf, props.includePreview);
    if (current === requestId) history.value = result;
  } catch (reason) {
    if (current === requestId) error.value = getParsedApiError(reason);
  } finally {
    if (current === requestId) loading.value = false;
  }
}
watch(() => [props.market, props.asOf, props.includePreview, props.refreshKey], () => void load(), { immediate: true });
onBeforeUnmount(() => { requestId++; });
const hasRanks = computed(() => history.value?.series.some(series => series.ranks.some(rank => rank != null)));
const option = computed<ComposeOption<LineSeriesOption | GridComponentOption | LegendComponentOption | TooltipComponentOption>>(() => {
  const dark = resolvedTheme.value === 'dark';
  const text = dark ? '#e5e5e5' : '#262626';
  const muted = dark ? '#a3a3a3' : '#525252';
  const split = dark ? 'rgba(255,255,255,.12)' : 'rgba(0,0,0,.08)';
  const data = history.value;
  return {
    animation: false,
    tooltip: {
      trigger: 'item', confine: true, renderMode: 'richText',
      backgroundColor: dark ? '#262626' : '#ffffff', borderColor: split, textStyle: { color: text },
      formatter: params => {
        const point = Array.isArray(params) ? params[0] : params;
        if (!point) return '';
        const date = data?.dates[point.dataIndex];
        const series = data?.series[point.seriesIndex ?? 0];
        const rank = series?.ranks[point.dataIndex];
        return `${date}${date === data?.previewDate ? ' · Preview' : ''}\n${series?.name} / ${series?.code}\nRank: ${rank == null ? '—' : `#${rank}`}`;
      },
    },
    legend: {
      type: 'plain', top: 0, left: 0, right: 0,
      textStyle: { color: muted, fontSize: 11 },
    },
    grid: { left: 12, right: 16, top: 160, bottom: 12, containLabel: true },
    xAxis: {
      type: 'category', data: data?.dates ?? [],
      axisLabel: { color: muted, hideOverlap: true, formatter: (value: string) => value.slice(5) },
      axisLine: { lineStyle: { color: split } }, axisTick: { show: false },
    },
    yAxis: {
      type: 'value', inverse: true, min: 1, minInterval: 1,
      max: Math.max(2, ...(data?.series.flatMap(series => series.ranks.map(rank => rank ?? 1)) ?? [])),
      axisLabel: { color: muted, formatter: '#{value}' }, splitLine: { lineStyle: { color: split } },
    },
    series: data?.series.map(series => ({
      name: series.name, type: 'line', smooth: 0.25, connectNulls: false,
      showSymbol: true, symbol: 'circle', symbolSize: 3, lineStyle: { width: 1 },
      emphasis: { focus: 'series', lineStyle: { width: 2 } },
      data: series.ranks.map((rank, index) => data.dates[index] === data.previewDate
        ? { value: rank, symbol: 'emptyCircle', symbolSize: 8 } : rank),
    })) ?? [],
  };
});
</script>

<template>
  <section
    class="min-w-0 rounded-xl border bg-card p-4 text-card-foreground"
    data-testid="etf-rank-history"
    aria-label="ETF 排名走势"
    :aria-busy="loading"
  >
    <h3 class="font-semibold">
      ETF 排名走势
    </h3>
    <p class="mt-1 text-xs text-muted-foreground">
      最近 30 个有正式快照的交易日{{ asOf ? ` · 截至 ${asOf}` : '' }} · 排名提升时曲线上移 · 点击图例可隐藏或显示 ETF
    </p>
    <p
      v-if="loading"
      class="py-16 text-center text-sm text-muted-foreground"
    >
      正在加载排名历史…
    </p>
    <div
      v-else-if="error"
      class="mt-4 space-y-2"
    >
      <AppApiErrorAlert :error="error" />
      <Button
        variant="outline"
        size="sm"
        @click="load"
      >
        重试排名历史
      </Button>
    </div>
    <template v-else>
      <div
        v-if="hasRanks"
        class="mt-4 h-[30rem] min-w-0"
      >
        <VChart
          :option="option"
          :update-options="{ notMerge: true }"
          autoresize
          role="img"
          aria-label="ETF Rank 历史折线图，Rank 1 位于最上方，缺失排名保留断点"
        />
      </div>
      <p
        v-else
        class="py-16 text-center text-sm text-muted-foreground"
      >
        暂无排名历史
      </p>
      <p
        v-if="history"
        class="mt-3 text-xs text-muted-foreground"
      >
        已有 {{ history.officialCount }} 个正式快照交易日 · 缺失 Rank 不补值
        <span v-if="history.generatedAt"> · 正式数据更新时间：{{ formatFullDateTimeWithTimezone(history.generatedAt) }}</span>
      </p>
      <p
        v-if="history?.previewDate"
        class="mt-2 text-sm text-amber-700 dark:text-amber-400"
      >
        {{ history.previewDate }} 最后一个空心点为 Preview（不计入 30 个正式交易日），盘中排名可能变化。
        <span v-if="history.previewTime">更新时间：{{ formatFullDateTimeWithTimezone(history.previewTime) }}</span>
      </p>
    </template>
  </section>
</template>
