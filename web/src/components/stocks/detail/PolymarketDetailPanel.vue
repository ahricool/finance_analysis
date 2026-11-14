<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { predictionApi, type SearchResult } from '@/api/predictionMarkets';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import PredictionEventCard from '@/components/prediction-markets/PredictionEventCard.vue';
import { Button } from '@/components/ui/button';
import { formatDateTimeInDisplayTimezone as dateTime } from '@/utils/format';
import type { StockDetailPanelProps } from './types';

const props = defineProps<StockDetailPanelProps>();
const data = ref<SearchResult>();
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
let controller: AbortController | undefined;
let generation = 0;
async function load() {
  controller?.abort();
  const request = ++generation;
  const current = controller = new AbortController();
  loading.value = true; error.value = null; data.value = undefined;
  try {
    const result = await predictionApi.search(props.symbol, current.signal);
    if (request === generation) data.value = result;
  } catch (cause) {
    if (request === generation && !current.signal.aborted) error.value = getParsedApiError(cause);
  } finally { if (request === generation) loading.value = false; }
}
watch(() => props.symbol, load, { immediate: true });
onBeforeUnmount(() => { ++generation; controller?.abort(); });
</script>
<template>
  <section
    class="min-w-0 space-y-4"
    data-testid="polymarket-detail-panel"
  >
    <div class="flex flex-wrap items-center justify-between gap-2">
      <p class="text-sm text-muted-foreground">
        股票名称 / 代码搜索 · 官方搜索排序 · 最多 20 条未关闭事件。关键词命中不代表已确认对该股票有影响。
      </p>
      <Button
        variant="outline"
        size="sm"
        :disabled="loading"
        @click="load"
      >
        刷新
      </Button>
    </div>
    <p
      v-if="loading"
      role="status"
    >
      正在搜索 Polymarket…
    </p>
    <AppApiErrorAlert
      v-else-if="error"
      :error="error"
      action-label="重试搜索"
      @action="load"
    />
    <template v-else-if="data?.status === 'ready'">
      <p class="text-xs text-muted-foreground">
        搜索词：{{ data.queries.join(' / ') }} · {{ data.items.length }} 条 · 获取于 {{ data.fetchedAt ? dateTime(data.fetchedAt) : '暂无' }}
        {{ data.stale ? ' · 上游暂不可用，展示旧缓存' : '' }}
      </p>
      <p
        v-if="data.partial"
        class="text-sm text-muted-foreground"
      >
        部分搜索请求失败，当前结果可能不完整，可稍后重试。
      </p>
      <p
        v-if="!data.items.length"
        class="text-sm text-muted-foreground"
      >
        未找到匹配的未关闭事件。
      </p>
      <PredictionEventCard
        v-for="event in data.items"
        :key="event.eventId"
        :event="event"
      />
    </template>
    <p
      v-else
      class="text-sm text-muted-foreground"
    >
      Polymarket 暂不可用，请稍后重试。
    </p>
  </section>
</template>
