<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue';
import { fetchIntradayMarket, type IntradayBar } from '@/api/intradayMarket';
import type { TrendResult } from '@/api/intradayOptions';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import { Button } from '@/components/ui/button';
import { useTheme } from '@/composables/useTheme';
import { clock, fmt, pct } from './labels';
import { referenceSeries, trendOverlays } from './overlays';

const props = defineProps<{ symbol: string; result: TrendResult | null; stale: boolean }>();
const selected = ref(30);
const mode = ref<'vwap' | 'mean' | 'off'>('vwap');
const rows = shallowRef<IntradayBar[]>([]);
const error = shallowRef<ParsedApiError | null>(null);
const loading = ref(true);
const chartDate = ref('');
const { resolvedTheme } = useTheme();
const panel = ref<HTMLElement>();
const panelWidth = ref('100%');
let observer: ResizeObserver | undefined;
onMounted(() => {
  const container = panel.value?.closest('[data-slot="table-container"]');
  if (container) {
    const resize = () => { panelWidth.value = `${Math.max(240, container.clientWidth - 24)}px`; };
    resize(); observer = new ResizeObserver(resize); observer.observe(container);
  }
});
const closed = computed(() => rows.value.filter(b => b.confirmed));
const bars = computed(() => closed.value.map(b => ({ ...b, turnover: b.turnover ?? undefined })));
const current = computed(() => {
  const b = rows.value.find(row => !row.confirmed);
  return b ? { ...b, turnover: b.turnover ?? undefined } : null;
});
const window = computed(() => props.result?.windows.find(w => w.minutes === selected.value));
const overlays = computed(() => trendOverlays(closed.value, window.value, mode.value, resolvedTheme.value === 'dark'));
const referenceLabel = computed(() => mode.value === 'off' ? '参考线已隐藏' : referenceSeries(closed.value, mode.value).label);
let controller: AbortController | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let generation = 0, stopped = false;
async function load() {
  if (stopped || controller) return;
  const owner = generation;
  const request = new AbortController(); controller = request;
  try {
    const since = rows.value.at(-1)?.timestamp;
    const result = await fetchIntradayMarket(props.symbol, since == null ? undefined : new Date(since).toISOString(), request.signal);
    if (stopped || owner !== generation) return;
    const merged = new Map((result.reset || result.fullSnapshot ? [] : rows.value).map(b => [b.timestamp, b]));
    result.items.forEach(b => merged.set(b.timestamp, b));
    rows.value = [...merged.values()].sort((a, b) => a.timestamp - b.timestamp);
    chartDate.value = result.tradingDate;
    error.value = null;
  } catch (reason) {
    if (!stopped && owner === generation && !request.signal.aborted) error.value = getParsedApiError(reason);
  } finally {
    if (owner === generation) { controller = null; loading.value = false; if (!stopped) timer = setTimeout(() => { void load(); }, 5000); }
  }
}
watch(() => props.symbol, () => {
  generation++; controller?.abort(); controller = null; clearTimeout(timer); rows.value = []; chartDate.value = '';
  loading.value = true; error.value = null; void load();
}, { immediate: true });
onBeforeUnmount(() => { stopped = true; generation++; controller?.abort(); clearTimeout(timer); observer?.disconnect(); });
</script>

<template>
  <section
    ref="panel"
    :style="{ width: panelWidth }"
    class="sticky left-3 min-w-0 whitespace-normal break-words space-y-3 rounded-lg border bg-muted/20 p-3"
    data-testid="options-trend-panel"
  >
    <div class="flex flex-wrap items-center justify-between gap-2">
      <strong class="text-sm">{{ symbol }} · {{ chartDate || '当日' }} · 1分钟K线</strong>
      <span class="text-xs text-muted-foreground">纽约时间 · 未闭合K不参与评分</span>
    </div>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-xs text-muted-foreground">观察范围</span>
      <Button
        v-for="n in [15, 30, 60]"
        :key="n"
        size="sm"
        :variant="selected === n ? 'secondary' : 'ghost'"
        :aria-pressed="selected === n"
        @click="selected = n"
      >
        {{ n }}分钟
      </Button>
      <span class="ml-2 text-xs text-muted-foreground">参考线</span>
      <Button
        v-for="item in [{ key: 'vwap', label: 'VWAP' }, { key: 'mean', label: '等权均价' }, { key: 'off', label: '隐藏' }] as const"
        :key="item.key"
        size="sm"
        :variant="mode === item.key ? 'secondary' : 'ghost'"
        :aria-pressed="mode === item.key"
        @click="mode = item.key"
      >
        {{ item.label }}
      </Button>
    </div>
    <MarketKLineChart
      v-if="rows.length"
      :symbol="symbol"
      period="1m"
      :bars="bars"
      :current="current"
      :overlays="overlays"
      timezone="America/New_York"
    />
    <p
      v-else
      class="py-10 text-center text-sm text-muted-foreground"
    >
      {{ loading ? '加载分钟行情…' : '暂无当日分钟线；不会补造缺失K线。' }}
    </p>
    <p class="text-xs text-muted-foreground">
      {{ referenceLabel }}。紫色区域仅标记所选窗口；窗口尚未完整时不标记。
    </p>
    <div class="grid gap-3 md:grid-cols-3">
      <article
        v-for="w in result?.windows ?? []"
        :key="w.minutes"
        class="space-y-1 rounded border p-3 text-xs"
        :class="selected === w.minutes ? 'border-brand/50' : ''"
      >
        <p class="text-sm font-medium">
          {{ w.minutes }}分钟 · {{ fmt(w.score) }}分 · {{ pct(w.returnPct) }}
        </p>
        <p
          v-if="w.dataStatus !== 'ready'"
          class="text-muted-foreground"
        >
          {{ w.dataStatus === 'gap' ? '分钟缺失，暂停此窗口评分' : '等待窗口预热' }}
        </p>
        <template v-else>
          <p>稳定度 {{ fmt(w.stability) }} · 路径效率 {{ fmt(w.efficiency) }}</p>
          <p>移动强度 {{ fmt(w.strength) }} · 扰动控制 {{ fmt(w.disturbance) }}</p>
          <p>标准化移动 {{ fmt(w.normalizedMove, 2) }} · 逆向幅度 {{ fmt(w.adverseMove, 2) }}</p>
          <p>最长逆向占比 {{ fmt((w.adverseDuration ?? 0) * 100) }}% · 移动门槛系数 {{ fmt(w.movementGate, 2) }}</p>
          <p>单分钟移动集中度 {{ fmt((w.concentration ?? 0) * 100) }}%</p>
          <p class="text-muted-foreground">
            {{ clock(w.startAt) }}–{{ clock(w.endAt) }}
          </p>
          <p
            v-for="reason in w.reasons"
            :key="reason"
            class="text-amber-600 dark:text-amber-400"
          >
            {{ reason }}
          </p>
        </template>
      </article>
    </div>
    <div class="space-y-1 text-sm">
      <p
        v-if="stale"
        class="text-amber-600 dark:text-amber-400"
      >
        以下为上次计算结果，不代表当前行情。
      </p>
      <p>{{ result?.explanation ?? '等待行情与完整窗口。' }}</p>
      <p class="text-xs text-muted-foreground">
        评分截至 {{ clock(result?.asOf) }} · 基础分 {{ fmt(result?.baseScore) }} · 方向一致性 {{ fmt(result?.alignment, 2) }} · 短线偏离 {{ fmt(result?.extensionAtr, 2) }} ATR
      </p>
      <p class="text-xs text-muted-foreground">
        窗口权重：稳定度30% / 路径效率30% / 移动强度25% / 扰动控制15%；综合窗口权重15m/30m/60m = 30%/45%/25%。趋势机会分不是盈利概率。
      </p>
    </div>
  </section>
</template>
