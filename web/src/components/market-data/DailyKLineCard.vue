<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { marketDataApi, type DailyBarsResponse } from '@/api/marketData';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import MarketKLineChart from './MarketKLineChart.vue';

const props = defineProps<{ symbol: string; endDate?: string }>();
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const data = ref<DailyBarsResponse | null>(null);
let controller: AbortController | undefined;
const bars = computed(() => (data.value?.items ?? [])
  .filter(row => !props.endDate || row.tradeDate <= props.endDate)
  .map(row => ({ timestamp: Date.parse(`${row.tradeDate}T00:00:00Z`), open: row.open,
    high: row.high, low: row.low, close: row.close, volume: row.volume, turnover: row.amount ?? undefined })));
// Use displayed OHLC only; cap at four places and ignore floating-point noise beyond that.
const pricePrecision = computed(() => bars.value.reduce((precision, bar) => {
  for (const value of [bar.open, bar.high, bar.low, bar.close]) {
    if (!Number.isFinite(value)) continue;
    const decimals = value.toFixed(4).replace(/0+$/, '').split('.')[1]?.length ?? 0;
    precision = Math.max(precision, decimals);
  }
  return precision;
}, 2));
async function load() {
  controller?.abort();
  const request = new AbortController();
  controller = request;
  data.value = null;
  error.value = null;
  loading.value = true;
  try {
    const result = await marketDataApi.dailyBars(props.symbol, props.endDate, undefined, request.signal);
    if (!request.signal.aborted) data.value = result;
  } catch (e) {
    if (!request.signal.aborted) error.value = getParsedApiError(e);
  } finally {
    if (!request.signal.aborted) loading.value = false;
  }
}
watch(() => [props.symbol, props.endDate], load, { immediate: true });
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <section
    class="min-w-0 rounded-xl border bg-card p-4"
    data-testid="daily-kline-card"
  >
    <h3 class="mb-3 text-sm font-semibold">
      日 K
    </h3>
    <p
      v-if="loading"
      class="py-12 text-center text-sm text-muted-foreground"
      role="status"
    >
      日 K 加载中…
    </p>
    <AppApiErrorAlert
      v-else-if="error"
      :error="error"
      action-label="重试"
      @action="load"
    />
    <p
      v-else-if="!bars.length"
      class="py-12 text-center text-sm text-muted-foreground"
    >
      暂无日 K 数据
    </p>
    <MarketKLineChart
      v-else
      :symbol="data?.symbol ?? symbol"
      period="1d"
      :price-precision="pricePrecision"
      :bars="bars"
      :source-key="`${symbol}:${endDate ?? 'latest'}`"
    />
  </section>
</template>
