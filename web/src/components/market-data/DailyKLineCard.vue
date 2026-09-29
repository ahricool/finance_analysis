<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { marketDataApi, type DailyBarsResponse } from '@/api/marketData';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import StockMembershipTags from '@/components/stocks/StockMembershipTags.vue';
import MarketKLineChart from './MarketKLineChart.vue';
import { tradeMarkerOverlays } from './tradeMarkerOverlay';
import type { TradeMarker } from '@/lib/tradeMarkers';

const props = defineProps<{ symbol: string; endDate?: string; highlightDate?: string; markers?: TradeMarker[]; markerCaption?: string }>();
const selected = ref<TradeMarker | null>(null);
const focusTimestamp = ref<number>();
const focusRequest = ref(0);
function navigate(timestamp?: number) {
  focusTimestamp.value = timestamp;
  focusRequest.value++;
}
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const data = ref<DailyBarsResponse | null>(null);
let controller: AbortController | undefined;
const bars = computed(() => (data.value?.items ?? [])
  .filter(row => !props.endDate || row.tradeDate <= props.endDate)
  .map(row => ({ timestamp: Date.parse(`${row.tradeDate}T00:00:00Z`), open: row.open,
    high: row.high, low: row.low, close: row.close, volume: row.volume, turnover: row.amount ?? undefined })));
const tradeOverlays = computed(() => tradeMarkerOverlays(props.markers ?? [], timestamp => {
  const bar = bars.value.find(item => item.timestamp === timestamp) ?? bars.value.at(-1);
  return bar?.close ?? 0;
}, marker => { selected.value = marker; }));
const highlightedBar = computed(() => bars.value.find(bar =>
  bar.timestamp === Date.parse(`${props.highlightDate}T00:00:00Z`)));
const overlays = computed(() => {
  const bar = highlightedBar.value;
  return [...tradeOverlays.value, ...(bar ? [{
    name: 'tradeBst', id: 'research-date', groupId: 'strategy-markers', lock: true,
    points: [{ timestamp: bar.timestamp, value: bar.high }],
    extendData: { label: `查看日 ${props.highlightDate}`, kind: 'date' },
  }] : [])];
});
function historyStart() {
  if (!props.highlightDate) return undefined;
  const day = new Date(`${props.highlightDate}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() - 365);
  return day.toISOString().slice(0, 10);
}
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
  focusTimestamp.value = undefined;
  const request = new AbortController();
  controller = request;
  data.value = null;
  error.value = null;
  loading.value = true;
  try {
    const result = await marketDataApi.dailyBars(props.symbol, props.endDate, historyStart(), request.signal);
    if (!request.signal.aborted) data.value = result;
  } catch (e) {
    if (!request.signal.aborted) error.value = getParsedApiError(e);
  } finally {
    if (!request.signal.aborted) loading.value = false;
  }
}
watch(() => [props.symbol, props.endDate, props.highlightDate], load, { immediate: true });
watch(() => props.markers, () => { selected.value = null; });
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <section
    class="min-w-0 rounded-xl border bg-card p-4"
    data-testid="daily-kline-card"
  >
    <div class="mb-3 flex min-h-6 items-center gap-3">
      <h3 class="shrink-0 text-sm font-semibold">
        日 K
      </h3>
      <StockMembershipTags :code="symbol" />
      <span
        v-if="highlightDate && !loading && !error"
        class="text-xs text-muted-foreground"
      >
        查看日 {{ highlightDate }} · {{ highlightedBar ? '↓ 图中标记' : '当日无 K 线' }} · 行情至 {{ data?.items?.at(-1)?.tradeDate ?? '—' }}
      </span>
      <template v-if="highlightedBar && !loading">
        <Button
          size="sm"
          variant="outline"
          @click="navigate(highlightedBar.timestamp)"
        >
          定位查看日
        </Button>
        <Button
          size="sm"
          variant="ghost"
          @click="navigate()"
        >
          最新行情
        </Button>
      </template>
    </div>
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
      :overlays="overlays"
      :bars="bars"
      :focus-timestamp="focusTimestamp"
      :focus-request="focusRequest"
      :source-key="`${symbol}:${endDate ?? 'latest'}`"
    />
    <div
      v-if="selected"
      class="mt-3 rounded border p-3 text-sm"
      data-testid="trade-marker-detail"
    >
      <strong>{{ markerCaption || '操作 BST' }} · {{ selected.type }}</strong>
      <p
        v-for="(item, index) in selected.operations"
        :key="index"
      >
        {{ item.executedAt }} {{ item.side === 'BUY' ? '买入' : item.side === 'SELL' ? '卖出' : item.side }}{{ item.quantity ? item.quantity : '' }}{{ item.price ? ` @${item.price}` : '' }}
      </p>
    </div>
  </section>
</template>
