<script setup lang="ts">
import { computed } from 'vue';
import type { Candle, ContractQuote } from '@/api/contracts';
import type { ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import TableExpansionPanel from '@/components/market-data/TableExpansionPanel.vue';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import { Button } from '@/components/ui/button';
import { useCurrentTime } from '@/composables/useCurrentTime';
import { signedTextClass } from '@/utils/marketTone';

const props = defineProps<{
  row: ContractQuote;
  interval: '1m' | '1d';
  bars: Candle[];
  current: Candle | null;
  loading: boolean;
  error: ParsedApiError | null;
}>();
const emit = defineEmits<{ 'update:interval': [value: '1m' | '1d']; retry: [] }>();
const now = useCurrentTime(5_000);
const periodMs = computed(() => props.interval === '1m' ? 60_000 : 86_400_000);
const newest = computed(() => props.current ?? props.bars.at(-1));
const closed = computed(() => props.bars.filter(bar => bar.timestamp + periodMs.value <= now.value.getTime()));
const preview = computed(() => {
  const last = props.bars.at(-1);
  return props.current ?? (last && last.timestamp + periodMs.value > now.value.getTime() ? last : null);
});
const chartBars = computed(() => closed.value.map(bar => ({ ...bar })));
const chartCurrent = computed(() => preview.value ? { ...preview.value } : null);
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
function percent(value: number | null | undefined, digits = 2) {
  return value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(digits)}%`;
}
function time(value: number | undefined) {
  return value == null ? '—' : new Date(value).toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
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
          {{ interval === '1m' ? 'Binance 原生分钟线 · UTC' : 'UTC 日线 · 已收盘历史与当日预览' }}
          <span v-if="minuteDelayed"> · 分钟行情延迟</span>
        </p>
      </div>
      <div class="flex gap-2">
        <Button
          v-for="period in (['1m', '1d'] as const)"
          :key="period"
          size="sm"
          :variant="interval === period ? 'default' : 'outline'"
          :aria-pressed="interval === period"
          @click="emit('update:interval', period)"
        >
          {{ period === '1m' ? '1 分钟 K' : '日 K' }}
        </Button>
      </div>
    </div>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重试日线"
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
          timezone="UTC"
          live-snapshot
          disable-forecast
        />
        <div
          v-else
          class="flex min-h-60 items-center justify-center text-sm text-muted-foreground"
        >
          {{ loading ? '行情加载中…' : '暂无 K 线，等待后台采集' }}
        </div>
      </div>
      <aside
        class="space-y-3 text-sm"
        data-testid="contract-indicators"
      >
        <dl class="grid grid-cols-2 gap-3 xl:grid-cols-1">
          <div>
            <dt class="text-xs text-muted-foreground">
              最新价 / 24h 涨跌幅<span v-if="quoteDelayed"> · 延迟</span>
            </dt>
            <dd class="tabular-nums">
              {{ price(row.quote?.price) }} / <span :class="signedTextClass(row.quote?.change_pct)">{{ percent(row.quote?.change_pct) }}</span>
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">
              24h 成交额 (USDT)
            </dt>
            <dd class="tabular-nums">
              {{ amount(row.quote?.turnover) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">
              资金费率
            </dt>
            <dd class="tabular-nums">
              {{ percent(row.quote?.funding_rate == null ? null : row.quote.funding_rate * 100, 4) }}
            </dd>
          </div>
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
  </TableExpansionPanel>
</template>
