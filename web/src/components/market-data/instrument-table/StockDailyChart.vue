<script setup lang="ts">
import { ref, shallowRef, watch } from 'vue';
import type { KLineData } from 'klinecharts';
import { marketDataApi } from '@/api/marketData';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import MarketKLineChart from '../MarketKLineChart.vue';
import TableExpansionPanel from '../TableExpansionPanel.vue';
import { queueTableRequest } from '@/utils/tableRequests';

const props = defineProps<{ symbol: string }>();
const bars = shallowRef<KLineData[]>([]);
const loading = ref(false);
const error = shallowRef<ParsedApiError | null>(null);
const revision = ref(0);
watch([() => props.symbol, revision], async ([symbol], _, cleanup) => {
  const request = new AbortController();
  cleanup(() => request.abort());
  bars.value = [];
  error.value = null;
  loading.value = true;
  try {
    const result = await queueTableRequest(request.signal, () => marketDataApi.dailyBars(symbol, undefined, undefined, request.signal));
    if (!request.signal.aborted) bars.value = result.items.map(b => ({ ...b, timestamp: Date.parse(b.tradeDate + 'T00:00:00Z') }));
  } catch (reason) {
    const parsed = getParsedApiError(reason);
    if (!request.signal.aborted && parsed.status !== 404) error.value = parsed;
  } finally {
    if (!request.signal.aborted) loading.value = false;
  }
}, { immediate: true });
</script>

<template>
  <TableExpansionPanel>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重试"
      @action="revision++"
    />
    <MarketKLineChart
      v-else-if="bars.length"
      :symbol="symbol"
      period="1d"
      :bars="bars"
      timezone="UTC"
    />
    <p
      v-else
      class="py-8 text-center text-sm text-muted-foreground"
    >
      {{ loading ? '加载日 K 线…' : '无数据' }}
    </p>
  </TableExpansionPanel>
</template>
