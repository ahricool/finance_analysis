<script setup lang="ts">
import { displayTimezoneLabel, getDisplayTimezone, formatFullDateTimeWithTimezone as time } from '@/utils/format';
import { computed, ref, watch } from 'vue';
import { structureLabels, structurePhases } from '@/components/intraday-options/labels';
import { detectDailyPatterns, type DailyPatternEvent } from '@/utils/dailyPatterns';
import { dailyPatternOverlays } from '@/components/market-data/dailyPatternOverlay';
import { useTheme } from '@/composables/useTheme';
import ContractMetricHistory from './ContractMetricHistory.vue';
import { contractsApi, type Depth, type Candle, type ContractQuote } from '@/api/contracts';
import type { ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import TableExpansionPanel from '@/components/market-data/TableExpansionPanel.vue';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import { useCurrentTime } from '@/composables/useCurrentTime';
import { signedTextClass } from '@/utils/marketTone';

import { queueTableRequest } from '@/utils/tableRequests';

const props = defineProps<{
  row: ContractQuote;
  interval: '1m' | '1d';
  bars: Candle[];
  current: Candle | null;
  loading: boolean;
  error: ParsedApiError | null;
}>();
const emit = defineEmits<{ retry: [] }>();
const now = useCurrentTime(5_000);
const depth = ref<Depth | null>(null);
watch(() => props.row.symbol, (symbol, _, cleanup) => {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  depth.value = null;
  async function refresh() {
    try {
      const snapshot = await queueTableRequest(controller.signal, () => contractsApi.depth(symbol, controller.signal));
      if (!controller.signal.aborted) depth.value = snapshot;
    } catch { if (!controller.signal.aborted) depth.value = null; }
    if (!controller.signal.aborted) timer = setTimeout(refresh, 5000);
  }
  cleanup(() => { controller.abort(); clearTimeout(timer); });
  void refresh();
}, { immediate: true });
const ratioKinds = [
  { key: 'accounts', label: '全市场账户' }, { key: 'top_accounts', label: '大户账户' },
  { key: 'top_positions', label: '大户仓位规模' },
] as const;
function share(value?: number | null) { return value == null ? '—' : (value * 100).toFixed(2) + '%'; }
function ratio(value?: number | null) { return value == null ? '—' : value.toFixed(2) + ' 倍'; }
const freshDepth = computed(() => depth.value && Math.abs(now.value.getTime() - depth.value.timestamp) < 15000 ? depth.value : null);
const periodMs = computed(() => props.interval === '1m' ? 60_000 : 86_400_000);
const newest = computed(() => props.current ?? props.bars.at(-1));
const closed = computed(() => props.bars.filter(bar => bar.timestamp + periodMs.value <= now.value.getTime()));
const preview = computed(() => {
  const last = props.bars.at(-1);
  return props.current ?? (last && last.timestamp + periodMs.value > now.value.getTime() ? last : null);
});
const chartBars = computed(() => closed.value.map(bar => ({ ...bar })));
const chartCurrent = computed(() => preview.value ? { ...preview.value } : null);
const { resolvedTheme } = useTheme();
const selectedPattern = ref<DailyPatternEvent | null>(null);
watch(() => [props.row.symbol, props.interval], () => { selectedPattern.value = null; });
const dailyBars = computed(() => props.interval === '1d' ? closed.value.map(bar => ({
  ...bar, amount: bar.turnover, tradeDate: new Date(bar.timestamp).toISOString().slice(0, 10),
})) : []);
const patterns = computed(() => detectDailyPatterns(dailyBars.value, { marketDate: now.value.toISOString().slice(0, 10) }));
const overlays = computed(() => dailyPatternOverlays(patterns.value, dailyBars.value, resolvedTheme.value === 'dark',
  event => { selectedPattern.value = event; }));
const precision = computed(() => {
  const price = props.row.quote?.price ?? newest.value?.close ?? 1;
  return price >= 100 ? 2 : price > 0 ? Math.max(2, Math.min(10, 3 - Math.floor(Math.log10(price)))) : 2;
});
const quoteDelayed = computed(() => !!props.row.quote && Math.abs(now.value.getTime() - props.row.quote.timestamp) > 60_000);
const minuteDelayed = computed(() => props.interval === '1m' && !!newest.value && now.value.getTime() - newest.value.timestamp > 120_000);
function price(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: precision.value });
}
function amount(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: 2 });
}
function percent(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function ma(length: number) {
  const window = closed.value.slice(-length);
  if (window.length !== length || window.some((bar, i) => i > 0 && bar.timestamp - window[i - 1]!.timestamp !== periodMs.value)) return null;
  return window.reduce((total, bar) => total + bar.close, 0) / length;
}
const maPeriods = computed(() => props.interval === '1m' ? [20] : [5, 10, 20]);
</script>

<template>
  <TableExpansionPanel data-testid="contract-market-panel">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <strong class="text-sm">{{ row.symbol }} · {{ interval === '1m' ? '最近 24 小时分钟行情' : '日线行情' }}</strong>
        <p class="text-xs text-muted-foreground">
          {{ interval === '1m' ? 'Binance 原生分钟线' : '交易所日线 · 已收盘历史与当日预览' }} · {{ displayTimezoneLabel() }}
          <span v-if="minuteDelayed"> · 分钟行情延迟</span>
        </p>
      </div>
    </div>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重试"
      @action="emit('retry')"
    />
    <div class="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_240px]">
      <div class="min-w-0">
        <MarketKLineChart
          v-if="closed.length || preview"
          :key="row.symbol + interval"
          :symbol="row.symbol"
          :period="interval"
          :bars="chartBars"
          :current="chartCurrent"
          :price-precision="precision"
          :timezone="interval === '1m' ? getDisplayTimezone() : undefined"
          live-snapshot
          contract-forecast
          :overlays="overlays"
        />
        <div
          v-else
          class="flex min-h-60 items-center justify-center text-sm text-muted-foreground"
        >
          {{ loading ? '行情加载中…' : '无数据 · 暂无 K 线' }}
        </div>
        <p
          v-if="interval === '1m' && row.analysis?.structure"
          class="mt-2 flex items-center gap-2 text-sm"
        >
          <strong>{{ structureLabels[row.analysis.structure.kind] }}</strong>
          <span class="text-muted-foreground">{{ structurePhases[row.analysis.structure.phase] }}</span>
          <small v-if="row.analysis.structure.reference || now.getTime() - row.analysis.as_of >= 90000">参考</small>
        </p>
        <p
          v-if="interval === '1d' && (selectedPattern || patterns.length)"
          class="mt-2 text-sm"
        >
          <strong>{{ (selectedPattern ?? patterns.at(-1))?.name }}</strong>
          <span class="ml-2 text-muted-foreground">{{ (selectedPattern ?? patterns.at(-1))?.date }}</span>
        </p>
      </div>
      <aside
        class="space-y-3 text-sm"
        data-testid="contract-indicators"
      >
        <dl>
          <dt class="text-xs text-muted-foreground">
            最新价 / 24h 涨跌幅<span v-if="quoteDelayed"> · 延迟</span>
          </dt>
          <dd class="tabular-nums">
            {{ price(row.quote?.price) }} / <span :class="signedTextClass(row.quote?.change_pct)">{{ percent(row.quote?.change_pct) }}</span>
          </dd>
        </dl>
        <div class="border-t pt-3">
          <p class="text-xs text-muted-foreground">
            {{ interval === '1m' ? '分钟' : '日线' }}均线 · 已结束 K 线
          </p>
          <dl class="mt-1 grid grid-cols-2 gap-x-2 gap-y-1 tabular-nums">
            <template
              v-for="length in maPeriods"
              :key="length"
            >
              <dt>MA{{ length }}</dt><dd class="text-right">
                {{ price(ma(length)) }}
              </dd>
            </template>
          </dl>
          <p class="mt-1 text-xs text-muted-foreground">
            连续窗口不足时留空
          </p>
        </div>
        <div class="border-t pt-3">
          <p class="text-xs text-muted-foreground">
            最新 K 线{{ preview ? '（预览）' : '' }}
          </p>
          <dl class="mt-1 grid grid-cols-2 gap-x-2 gap-y-1 tabular-nums">
            <dt>开盘</dt><dd class="text-right">
              {{ price(newest?.open) }}
            </dd>
            <dt>最高</dt><dd class="text-right">
              {{ price(newest?.high) }}
            </dd>
            <dt>最低</dt><dd class="text-right">
              {{ price(newest?.low) }}
            </dd>
            <dt>收盘</dt><dd class="text-right">
              {{ price(newest?.close) }}
            </dd>
          </dl>
        </div>
        <div class="space-y-1 text-xs text-muted-foreground">
          <p>行情：{{ time(row.quote?.timestamp) }}</p>
          <p>K 线：{{ time(newest?.timestamp) }}</p>
          <p>已采集 {{ closed.length + (preview ? 1 : 0) }} 根</p>
        </div>
      </aside>
    </div>
    <div class="grid gap-4 border-t pt-3 text-sm sm:grid-cols-2 xl:grid-cols-3">
      <section>
        <h3 class="font-semibold">
          多空结构
        </h3>
        <p class="text-xs text-muted-foreground">
          5 分钟截面 · {{ time(row.metrics?.timestamp) }}
        </p>
        <dl
          v-for="kind in ratioKinds"
          :key="kind.key"
          class="mt-2"
        >
          <dt>{{ kind.label }}多空比</dt>
          <dd>{{ ratio(row.metrics?.[kind.key]?.ratio) }} · 多 {{ share(row.metrics?.[kind.key]?.long) }} / 空 {{ share(row.metrics?.[kind.key]?.short) }}</dd>
          <dd
            v-if="row.metrics?.status[kind.key] === 'unauthorized'"
            class="text-xs text-muted-foreground"
          >
            缺少行情权限
          </dd>
        </dl>
      </section>
      <section>
        <h3 class="font-semibold">
          持仓量与主动成交
        </h3>
        <dl class="mt-2 space-y-1">
          <dt>OI 数量 / 名义价值</dt>
          <dd>{{ amount(row.metrics?.oi?.quantity) }} / {{ amount(row.metrics?.oi?.usdt) }} USDT</dd>
          <dt>5m 主动买量 / 卖量（标的数量）</dt>
          <dd>{{ amount(row.metrics?.taker?.buy) }} / {{ amount(row.metrics?.taker?.sell) }} · {{ ratio(row.metrics?.taker?.ratio) }}</dd>
          <dt>标记价 / 指数价 · 偏离率</dt>
          <dd>{{ price(row.mark?.mark_price) }} / {{ price(row.mark?.index_price) }} · {{ percent(row.mark?.basis == null ? null : row.mark.basis * 100) }}</dd>
          <dt>标记行情 / 下次资金结算</dt><dd>{{ time(row.mark?.timestamp) }} / {{ time(row.mark?.next_funding) }}</dd>
        </dl>
      </section>
      <section>
        <h3 class="font-semibold">
          盘口流动性
        </h3>
        <dl class="mt-2 space-y-1">
          <dt>最优买 / 卖 · 价差</dt>
          <dd>{{ price(row.book?.bid) }} / {{ price(row.book?.ask) }} · {{ amount(row.book?.spread_bps) }} bps</dd>
          <dd class="text-xs text-muted-foreground">
            {{ time(row.book?.timestamp) }}
          </dd>
          <dt>前 10 档名义额（USDT）</dt>
          <dd>买 {{ amount(freshDepth?.bids) }}（{{ freshDepth?.bids_levels ?? '—' }} 档） / 卖 {{ amount(freshDepth?.asks) }}（{{ freshDepth?.asks_levels ?? '—' }} 档）</dd>
          <dd class="text-xs text-muted-foreground">
            {{ time(freshDepth?.timestamp) }}
          </dd>
        </dl>
      </section>
    </div>
    <ContractMetricHistory
      :symbol="row.symbol"
      :boundary="row.metrics?.timestamp"
    />
  </TableExpansionPanel>
</template>
