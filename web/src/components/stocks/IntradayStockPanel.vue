<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue';
import type { OverlayCreate } from 'klinecharts';
import { fetchIntradayMarket, type IntradayBar, type IntradaySnapshot, type PatternEvent } from '@/api/intradayMarket';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import { ensureTradeMarkerOverlay } from '@/components/market-data/tradeMarkerOverlay';
import { Button } from '@/components/ui/button';
import TrendStatus from './TrendStatus.vue';
import PatternStatus from './PatternStatus.vue';
import IntradayDirectionStatus from './IntradayDirectionStatus.vue';
import { useCurrentTime } from '@/composables/useCurrentTime';

const props = defineProps<{ symbol: string; market: 'CN' | 'US' }>();
const panel = ref<HTMLElement>();
const panelWidth = ref('100%');
let resizeObserver: ResizeObserver | undefined;
onMounted(() => {
  const container = panel.value?.closest('[data-slot="table-container"]');
  if (container) {
    const resize = () => { panelWidth.value = `${Math.max(240, container.clientWidth - 24)}px`; };
    resize();
    resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);
  }
});
const snapshot = shallowRef<IntradaySnapshot | null>(null);
const rows = shallowRef<IntradayBar[]>([]);
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(true);
const selected = shallowRef<PatternEvent | null>(null);
const now = useCurrentTime();
const timezone = computed(() => props.market === 'CN' ? 'Asia/Shanghai' : 'America/New_York');
const toChartBar = (bar: IntradayBar) => ({ ...bar, turnover: bar.turnover ?? undefined });
const bars = computed(() => rows.value.filter(bar => bar.confirmed).map(toChartBar));
const current = computed(() => { const bar = rows.value.find(bar => !bar.confirmed); return bar ? toChartBar(bar) : null; });
const quote = computed(() => snapshot.value?.quote);
let request: AbortController | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let generation = 0;
let stopped = false;

function fmt(value: number | null | undefined) { return value == null ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: 3 }); }
function time(value: string | number | null | undefined) {
  return value == null ? '—' : new Date(value).toLocaleString('zh-CN', { timeZone: timezone.value, hour12: false });
}
async function load() {
  if (stopped || request) return;
  const owned = generation;
  const controller = new AbortController();
  request = controller;
  try {
    const since = rows.value.at(-1)?.timestamp;
    const value = await fetchIntradayMarket(props.symbol, since == null ? undefined : new Date(since).toISOString(), controller.signal);
    if (stopped || generation !== owned) return;
    const merged = new Map((value.reset ? [] : rows.value).map(row => [row.timestamp, row]));
    for (const row of value.items) merged.set(row.timestamp, row);
    rows.value = [...merged.values()].sort((a, b) => a.timestamp - b.timestamp);
    snapshot.value = value;
    if (value.reset) selected.value = null;
    error.value = null;
  } catch (reason) {
    if (!stopped && generation === owned && !controller.signal.aborted) error.value = getParsedApiError(reason);
  } finally {
    if (generation === owned) {
      request = null;
      loading.value = false;
      if (!stopped) timer = setTimeout(() => { void load(); }, 5_000);
    }
  }
}
watch(() => [props.symbol, props.market], () => {
  generation++;
  request?.abort(); request = null; clearTimeout(timer);
  snapshot.value = null; rows.value = []; selected.value = null; error.value = null; loading.value = true;
  void load();
}, { immediate: true });
onBeforeUnmount(() => { stopped = true; generation++; request?.abort(); clearTimeout(timer); resizeObserver?.disconnect(); });

const overlays = computed<OverlayCreate[]>(() => {
  ensureTradeMarkerOverlay();
  const result: OverlayCreate[] = [];
  for (const [index, event] of (snapshot.value?.events ?? []).entries()) {
    // Plot when the detector actually observed the event, never at an earlier structural pivot.
    const at = Date.parse(event.observed_at);
    const bar = [...rows.value].reverse().find(row => row.timestamp <= at);
    if (!bar || at - bar.timestamp > 120_000) continue;
    result.push({ name: 'tradeBst', id: `intraday-pattern-${index}`, groupId: 'intraday-patterns', lock: true,
      points: [{ timestamp: bar.timestamp, value: bar.high }],
      extendData: { label: `${event.pattern_name}·${event.stage === 'confirmed' ? '确认' : '观察'}`, kind: event.direction.startsWith('bullish') || event.direction === 'bearish_to_bullish' ? 'B' : 'S' },
      onClick: () => { selected.value = event; return true; } });
  }
  const evidence = selected.value ?? quote.value?.pattern_1m?.signal;
  for (const [label, value] of [['参考位', evidence?.reference_level], ['失效位', evidence?.invalidation_price]] as const) {
    if (value != null) result.push({ name: 'priceLine', id: `intraday-${label}`, groupId: 'intraday-levels', lock: true,
      points: [{ timestamp: rows.value.at(-1)?.timestamp ?? 0, value }], extendData: label });
  }
  return result;
});
const evidence = computed(() => selected.value ?? quote.value?.pattern_1m?.signal);
</script>

<template>
  <section
    ref="panel"
    :style="{ width: panelWidth }"
    class="sticky left-3 min-w-0 space-y-3 rounded-lg border bg-muted/20 p-3"
    data-testid="intraday-panel"
  >
    <div class="flex flex-wrap items-center justify-between gap-2 text-sm">
      <strong>最近交易日 1 分钟 K 线 · {{ snapshot?.trading_date ?? '加载中' }}</strong>
      <span class="text-xs text-muted-foreground">{{ market === 'CN' ? '扶摇 · 10秒采样近似K线 · 上海时间' : 'Longbridge · 原生分钟线 · 纽约时间' }}</span>
    </div>
    <ApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div
      v-if="loading"
      class="py-8 text-center text-sm text-muted-foreground"
    >
      加载分钟行情…
    </div>
    <div
      v-else
      class="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_240px]"
    >
      <div class="min-w-0">
        <MarketKLineChart
          v-if="rows.length"
          :symbol="symbol"
          period="1m"
          :bars="bars"
          :current="current"
          :overlays="overlays"
          :timezone="timezone"
        />
        <p
          v-else
          class="py-12 text-center text-sm text-muted-foreground"
        >
          暂无最近交易日分钟线，等待采集；缺失区间不会补造。
        </p>
        <p
          v-if="market === 'CN'"
          class="mt-2 text-xs text-muted-foreground"
        >
          采样可能遗漏分钟内价格极值；成交量为累计量差分估算，缺口与部分分钟不参与正式形态确认。
        </p>
      </div>
      <aside class="space-y-4 text-sm">
        <div>
          <p class="text-xs text-muted-foreground">
            最新价 / 当日涨跌幅
          </p><p>{{ fmt(quote?.last_price) }} / {{ fmt(quote?.change_pct) }}%</p>
        </div>
        <div>
          <p class="mb-1 text-xs text-muted-foreground">
            趋势持续
          </p><TrendStatus :trend="quote?.trend_1m" />
        </div>
        <div>
          <p class="mb-1 text-xs text-muted-foreground">
            最近形态
          </p><PatternStatus :pattern="quote?.pattern_1m" />
        </div>
        <div>
          <p class="mb-1 text-xs text-muted-foreground">
            日内方向状态
          </p><IntradayDirectionStatus
            :quote="quote"
            :market-type="market"
            :now="now"
          />
        </div>
        <div class="text-xs text-muted-foreground">
          <p>行情：{{ time(quote?.event_time) }}</p><p>接收：{{ time(quote?.received_at) }}</p><p>已采集 {{ rows.length }} 根 · 部分分钟 {{ rows.filter(row => row.partial).length }} 根</p>
        </div>
        <div
          v-if="evidence"
          class="space-y-1 border-t pt-3"
          data-testid="intraday-pattern-evidence"
        >
          <strong>{{ evidence.pattern_name }} · {{ evidence.stage === 'confirmed' ? '已确认' : '观察中' }}</strong>
          <p
            v-if="selected"
            class="text-xs"
          >
            首次观测：{{ time(selected.observed_at) }}
          </p>
          <p>参考位 {{ fmt(evidence.reference_level) }} / 失效位 {{ fmt(evidence.invalidation_price) }}</p>
          <p
            v-for="reason in evidence.reasons"
            :key="reason"
            class="text-xs text-muted-foreground"
          >
            {{ reason }}
          </p>
          <Button
            v-if="selected"
            size="sm"
            variant="ghost"
            @click="selected = null"
          >
            返回最近形态
          </Button>
        </div>
      </aside>
    </div>
  </section>
</template>
