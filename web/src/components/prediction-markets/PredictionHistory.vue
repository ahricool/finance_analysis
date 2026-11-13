<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { use } from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import VChart from 'vue-echarts';
import { predictionApi, type HistoryData } from '@/api/predictionMarkets';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { Button } from '@/components/ui/button';
import { formatDateTimeInDisplayTimezone as dateTime } from '@/utils/format';
import { useTimezoneStore } from '@/stores/timezoneStore';
import { useTheme } from '@/composables/useTheme';
use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);
const props = defineProps<{ eventId: string; marketId: string; outcomeId: string }>();
const window = ref('1w');
const data = ref<HistoryData>();
const error = ref<ParsedApiError | null>(null);
const loading = ref(false);
const { resolvedTheme } = useTheme();
const timezone = useTimezoneStore();
let controller: AbortController | undefined;
let generation = 0;
async function load() {
  controller?.abort(); controller = new AbortController(); const token = ++generation;
  data.value = undefined; error.value = null; loading.value = true;
  try { const result = await predictionApi.history(props.eventId, props.marketId, props.outcomeId, window.value, controller.signal); if (token === generation) data.value = result; }
  catch (cause) { if (token === generation && !controller.signal.aborted) error.value = getParsedApiError(cause); }
  finally { if (token === generation) loading.value = false; }
}
watch([() => props.eventId, () => props.marketId, () => props.outcomeId, window], load, { immediate: true });
onBeforeUnmount(() => { ++generation; controller?.abort(); });
const option = computed(() => {
  const displayTimezone = timezone.displayTimezone;
  const dark = resolvedTheme.value === 'dark';
  const color = dark ? '#d4d4d8' : '#52525b';
  const label = (v: number) => new Intl.DateTimeFormat('zh-CN', { timeZone: displayTimezone, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(v);
  return {
    animation: false, backgroundColor: 'transparent', textStyle: { color },
    grid: { left: 48, right: 16, top: 16, bottom: 50 },
    tooltip: { trigger: 'axis', renderMode: 'richText', formatter: (params: unknown) => {
      const point = (params as Array<{ value?: [number, number] }>)[0]?.value;
      return point ? `${label(point[0])}\n${point[1].toFixed(2)}%` : '';
    } },
    xAxis: { type: 'time', splitNumber: 3, axisLabel: { hideOverlap: true, formatter: (v: number) => label(v).replace(' ', '\n') } },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' }, splitLine: { lineStyle: { color: dark ? '#3f3f46' : '#e4e4e7' } } },
    series: [{ type: 'line', connectNulls: false, showSymbol: true, symbolSize: 3, smooth: false, lineStyle: { color }, itemStyle: { color },
      data: data.value?.points?.map(p => [p.timestamp * 1000, p.price * 100]) ?? [] }],
  };
});
const resolutions = computed(() => [...new Set(data.value?.points?.map(p => p.resolutionSeconds) ?? [])].sort((a, b) => a - b).join(' / '));
const reasons: Record<string, string> = { insufficient_history: '历史不足', closed_or_resolved: '已关闭或结算', latest_observation_stale_or_coarse: '最新观察过旧或粒度不足', baseline_stale_or_coarse: '基线过旧或粒度不足' };
</script>
<template>
  <section
    class="space-y-3 border-t pt-3"
    data-testid="prediction-history"
  >
    <div class="flex flex-wrap items-end gap-2">
      <FieldSelect
        v-model="window"
        class="w-40"
        label="历史窗口"
        :options="[{ value: '1d', label: '1天' }, { value: '1w', label: '1周' }, { value: '1m', label: '1月' }, { value: 'max', label: '全部可用历史' }]"
      />
      <Button
        variant="outline"
        :disabled="loading"
        @click="load"
      >
        刷新历史
      </Button>
    </div>
    <p
      v-if="loading"
      role="status"
    >
      读取历史中…
    </p>
    <AppApiErrorAlert
      v-else-if="error"
      :error="error"
      action-label="重试"
      @action="load"
    />
    <template v-else-if="data?.status === 'ready'">
      <p
        v-if="data.stale"
        class="text-sm text-muted-foreground"
      >
        上游暂不可用，显示短期旧缓存 · {{ dateTime(data.fetchedAt!) }}
      </p>
      <p class="text-xs text-muted-foreground">
        历史序列截至 {{ data.seriesAsOf ? dateTime(new Date(data.seriesAsOf * 1000).toISOString()) : '暂无' }} · 非当前报价差值
      </p>
      <div class="flex flex-wrap gap-4 text-sm">
        <span
          v-for="(change, key) in data.changes"
          :key="key"
        >{{ key }}：{{ change.percentagePoints == null ? `暂无（${reasons[change.reason ?? ''] ?? '历史不足'}）` : `${change.percentagePoints.toFixed(2)} 个百分点` }}</span>
      </div>
      <div
        v-if="data.points?.length"
        class="h-64 w-full"
        data-testid="prediction-history-chart"
      >
        <VChart
          :option="option"
          autoresize
        />
      </div>
      <p v-else>
        暂无该窗口历史。
      </p>
      <p class="text-xs text-muted-foreground">
        官方逐点分辨率（秒）：{{ resolutions || '暂无' }}。稀疏点不补齐；0表示精确观察，已结算时也可能为结算点。
      </p>
    </template>
    <p
      v-else
      class="text-sm"
    >
      历史暂不可用。<Button
        variant="link"
        @click="load"
      >
        重试
      </Button>
    </p>
  </section>
</template>
