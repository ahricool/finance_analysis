<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { predictionApi, type EventPage } from '@/api/predictionMarkets';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppPagination from '@/components/app/AppPagination.vue';
import PredictionEventCard from '@/components/prediction-markets/PredictionEventCard.vue';
import type { StockDetailPanelProps } from './types';
const props = defineProps<StockDetailPanelProps>();
const page = ref(1); const data = ref<EventPage>(); const error = ref<ParsedApiError | null>(null); const loading = ref(false);
let generation = 0; let controller: AbortController | undefined;
async function load() {
  controller?.abort(); controller = new AbortController(); const token = ++generation;
  data.value = undefined; error.value = null; loading.value = true;
  try { const result = await predictionApi.stock(props.symbol, page.value, controller.signal); if (token === generation) data.value = result; }
  catch (cause) { if (token === generation && !controller.signal.aborted) error.value = getParsedApiError(cause); }
  finally { if (token === generation) loading.value = false; }
}
watch([() => props.symbol, () => props.market], () => { page.value = 1; void load(); }, { immediate: true });
watch(page, load);
onBeforeUnmount(() => { ++generation; controller?.abort(); });
</script>
<template>
  <section
    class="space-y-4"
    data-testid="prediction-detail-panel"
  >
    <p class="text-sm text-muted-foreground">
      只显示该证券的事件关联；概率变化不等于股票利好或利空。
    </p>
    <p
      v-if="loading"
      role="status"
    >
      加载关联话题…
    </p>
    <AppApiErrorAlert
      v-else-if="error"
      :error="error"
      action-label="重试"
      @action="load"
    />
    <p v-else-if="data?.status === 'disabled'">
      事件预测功能未启用。
    </p>
    <p v-else-if="!data?.items.length">
      {{ data?.status === 'not_synced' ? '事件目录尚未同步。' : '暂无关联话题。' }}
    </p>
    <PredictionEventCard
      v-for="event in data?.items"
      :key="event.eventId"
      :event="event"
    />
    <AppPagination
      :current-page="page"
      :total-pages="Math.ceil((data?.total ?? 0) / 5)"
      @page-change="page = $event"
    />
  </section>
</template>
