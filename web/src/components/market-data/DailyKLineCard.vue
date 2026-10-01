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
import { detectDailyPatterns, dailyPatternMarketDate, type DailyPatternEvent } from '@/utils/dailyPatterns';
import { dailyPatternOverlays } from './dailyPatternOverlay';
import { useTheme } from '@/composables/useTheme';

const props = defineProps<{ symbol: string; endDate?: string; highlightDate?: string; markers?: TradeMarker[]; markerCaption?: string }>();
const selected = ref<TradeMarker | null>(null);
const selectedPattern = ref<DailyPatternEvent | null>(null);
const marketDate = ref<string>();
const { resolvedTheme } = useTheme();
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
const dailyBars = computed(() => (data.value?.items ?? [])
  .filter(row => !props.endDate || row.tradeDate <= props.endDate));
const patterns = computed(() => detectDailyPatterns(dailyBars.value, { marketDate: marketDate.value }));
const recentPatterns = computed(() => {
  const cutoff = dailyBars.value.at(-20)?.tradeDate ?? dailyBars.value[0]?.tradeDate ?? '';
  return patterns.value.filter(event => event.date >= cutoff).slice(-3).reverse();
});
const activePattern = computed(() => selectedPattern.value ?? recentPatterns.value[0]);
function patternAge(event: DailyPatternEvent) {
  const index = dailyBars.value.findIndex(bar => bar.tradeDate === event.date);
  const age = dailyBars.value.length - 1 - index;
  return age === 0 ? '最新交易日' : `${age} 个交易日前`;
}
const patternOverlays = computed(() => dailyPatternOverlays(patterns.value, dailyBars.value,
  resolvedTheme.value === 'dark', event => { selectedPattern.value = event; }));
const bars = computed(() => dailyBars.value.map(row => ({ timestamp: Date.parse(`${row.tradeDate}T00:00:00Z`), open: row.open,
    high: row.high, low: row.low, close: row.close, volume: row.volume, turnover: row.amount ?? undefined })));
const tradeOverlays = computed(() => tradeMarkerOverlays(props.markers ?? [], timestamp => {
  const bar = bars.value.find(item => item.timestamp === timestamp) ?? bars.value.at(-1);
  return bar?.close ?? 0;
}, marker => { selected.value = marker; }));
const highlightedBar = computed(() => bars.value.find(bar =>
  bar.timestamp === Date.parse(`${props.highlightDate}T00:00:00Z`)));
const overlays = computed(() => {
  const bar = highlightedBar.value;
  return [...tradeOverlays.value, ...patternOverlays.value, ...(bar ? [{
    name: 'tradeBst', id: 'research-date', groupId: 'research-date', lock: true,
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
  selected.value = null;
  selectedPattern.value = null;
  marketDate.value = undefined;
  focusTimestamp.value = undefined;
  const request = new AbortController();
  controller = request;
  data.value = null;
  error.value = null;
  loading.value = true;
  try {
    const result = await marketDataApi.dailyBars(props.symbol, props.endDate, historyStart(), request.signal);
    if (!request.signal.aborted) {
      marketDate.value = dailyPatternMarketDate(result.market, new Date());
      data.value = result;
    }
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
      v-if="data?.historyFallback && bars.length"
      class="mb-3 text-sm text-muted-foreground"
      role="status"
    >
      最新历史行情暂不可用，已保留已有数据。当前图表至 {{ data.items.at(-1)?.tradeDate ?? '—' }}。
    </p>
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
    <section
      v-if="!loading && !error && bars.length"
      class="mt-3 border-t pt-3 text-sm"
      data-testid="daily-pattern-summary"
      aria-label="Price Action 最近形态"
    >
      <div class="flex items-center justify-between gap-3">
        <h4 class="font-medium">
          Price Action · 最近形态
        </h4>
        <span class="text-xs text-muted-foreground">最近 20 个交易日 · Quality 为规则匹配分，非胜率</span>
      </div>
      <p
        v-if="!recentPatterns.length"
        class="mt-2 text-muted-foreground"
      >
        最近未发现高质量经典 K 线形态
      </p>
      <div
        v-if="recentPatterns.length"
        class="mt-2 flex flex-wrap gap-2"
      >
        <Button
          v-for="event in recentPatterns"
          :key="event.date"
          size="sm"
          :variant="activePattern?.date === event.date ? 'secondary' : 'ghost'"
          :aria-pressed="activePattern?.date === event.date"
          @click="selectedPattern = event; navigate(event.timestamp)"
        >
          {{ event.date.slice(5) }} {{ event.name }} · {{ event.quality }}{{ event.confirmed ? '' : ' · 形成中' }}
        </Button>
      </div>
      <div
        v-if="activePattern"
        class="mt-2 rounded border p-3"
        data-testid="daily-pattern-detail"
        aria-live="polite"
      >
        <div class="flex flex-wrap items-center gap-2">
          <strong :class="activePattern.direction === 'bullish' ? 'text-market-up' : 'text-market-down'">
            {{ activePattern.direction === 'bullish' ? '↑' : '↓' }} {{ activePattern.name }}
          </strong>
          <span>{{ activePattern.date }} · {{ patternAge(activePattern) }}</span>
          <span>Quality {{ activePattern.quality }}</span>
          <span :class="activePattern.confirmed ? 'text-muted-foreground' : 'rounded border border-dashed px-2'">
            {{ activePattern.confirmed ? 'Confirmed / 已完成日 K' : 'Preview / 形成中' }}
          </span>
        </div>
        <ul class="mt-2 list-inside list-disc text-xs leading-5 text-muted-foreground">
          <li
            v-for="reason in activePattern.reasons"
            :key="reason"
          >
            {{ reason }}
          </li>
        </ul>
        <p
          v-if="!activePattern.confirmed"
          class="mt-2 text-xs text-muted-foreground"
        >
          未取得收盘确认；市场当日 K 保守显示为形成中，收盘后也不自动升级。
        </p>
      </div>
    </section>
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
