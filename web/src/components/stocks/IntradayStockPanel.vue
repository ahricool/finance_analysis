<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue';
import type { OverlayCreate } from 'klinecharts';
import { fetchIntradayMarket, type IntradayBar, type IntradaySnapshot, type PatternEvent } from '@/api/intradayMarket';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import { intradayPatternOverlays } from './intradayPatternOverlay';
import { Button } from '@/components/ui/button';
import TrendStatus from './TrendStatus.vue';
import PatternStatus from './PatternStatus.vue';
import IntradayDirectionStatus from './IntradayDirectionStatus.vue';
import { useCurrentTime } from '@/composables/useCurrentTime';
import { useTheme } from '@/composables/useTheme';

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
const selectedEvents = shallowRef<PatternEvent[]>([]);
const { resolvedTheme } = useTheme();
function clearSelection() { selected.value = null; selectedEvents.value = []; }
const now = useCurrentTime(1_000);
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
    if (value.reset) clearSelection();
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
  snapshot.value = null; rows.value = []; clearSelection(); error.value = null; loading.value = true;
  void load();
}, { immediate: true });
onBeforeUnmount(() => { stopped = true; generation++; request?.abort(); clearTimeout(timer); resizeObserver?.disconnect(); });

const overlays = computed<OverlayCreate[]>(() => {
  const result = intradayPatternOverlays(snapshot.value?.events ?? [], rows.value, resolvedTheme.value === 'dark', events => {
    selectedEvents.value = events;
    selected.value = events[0] ?? null;
  });
  const evidence = selected.value;
  for (const [label, value] of [['参考位', evidence?.reference_level], ['失效位', evidence?.invalidation_price]] as const) {
    if (value != null) result.push({ name: 'priceLine', id: `intraday-${label}`, groupId: 'intraday-levels', lock: true,
      points: [{ timestamp: rows.value.at(-1)?.timestamp ?? 0, value }], extendData: label });
  }
  return result;
});
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
      <span class="text-xs text-muted-foreground">{{ market === 'CN' ? '扶摇 · 5秒采样近似K线 · 上海时间' : 'Longbridge · 原生分钟线 · 纽约时间' }}</span>
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
        <p
          v-if="rows.length"
          class="mt-2 text-xs text-muted-foreground"
        >
          <span class="text-market-up">▴ 多</span> · <span class="text-market-down">▾ 空</span> · ◇ 中性；同一分钟显示最新事件方向，点击标记查看详情与关键价位。
        </p>
        <div
          v-if="selected"
          class="mt-3 space-y-2 rounded border p-3 text-sm"
          data-testid="intraday-pattern-evidence"
          aria-live="polite"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <strong>{{ selected.pattern_name }} · {{ selected.stage === 'confirmed' ? '已确认' : selected.stage === 'forming' ? '形成中' : '观察中' }}</strong>
            <Button
              size="sm"
              variant="ghost"
              @click="clearSelection"
            >
              收起详情
            </Button>
          </div>
          <div
            v-if="selectedEvents.length > 1"
            class="flex flex-wrap gap-1"
            role="group"
            aria-label="同一分钟的形态事件"
          >
            <Button
              v-for="(event, index) in selectedEvents"
              :key="index"
              size="sm"
              :variant="selected === event ? 'secondary' : 'ghost'"
              :aria-pressed="selected === event"
              @click="selected = event"
            >
              {{ event.pattern_name }} · {{ event.stage === 'confirmed' ? '已确认' : event.stage === 'forming' ? '形成中' : '观察中' }}
            </Button>
          </div>
          <p class="text-xs text-muted-foreground">
            首次观测：{{ time(selected.observed_at) }} · Quality {{ selected.quality_score }}
          </p>
          <p>参考位 {{ fmt(selected.reference_level) }} / 失效位 {{ fmt(selected.invalidation_price) }}</p>
          <p
            v-for="reason in selected.reasons"
            :key="reason"
            class="text-xs text-muted-foreground"
          >
            {{ reason }}
          </p>
        </div>
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
      </aside>
    </div>
  </section>
</template>
