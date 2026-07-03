<script setup lang="ts">
import type { RealtimeQuote } from '@/api/realtimeMarket';
import type { MarketType } from '@/api/watchList';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import {
  formatDecimalText,
  formatHoldingCostAmount,
  formatMarketCurrencyAmount,
  getMarketCurrencyCode,
  getMarketCurrencySymbol,
} from '@/utils/marketCurrency';
import { X } from 'lucide-vue-next';
import { computed } from 'vue';

export interface StockDetailRecord {
  id: number;
  code: string;
  name: string | null;
  market_type: MarketType;
  notes?: string | null;
  is_favorite?: boolean;
  quantity?: string;
  avg_cost?: string | null;
  opened_at?: string | null;
  created_at: string;
  updated_at: string;
}

const props = defineProps<{
  stock: StockDetailRecord | null;
  quote?: RealtimeQuote;
  kind: 'watchlist' | 'holding';
}>();
defineEmits<{ close: [] }>();

const marketName = computed(() => ({ CN: 'A 股', HK: '港股', US: '美股' })[props.stock?.market_type ?? 'CN']);
const currencyCode = computed(() => getMarketCurrencyCode(props.stock?.market_type));
const holdingMarketValue = computed(() => {
  if (props.kind !== 'holding' || !props.quote?.available) return null;
  const quantity = Number(props.stock?.quantity);
  const lastPrice = props.quote.last_price;
  return Number.isFinite(quantity) && lastPrice !== null && lastPrice !== undefined && Number.isFinite(lastPrice)
    ? quantity * lastPrice
    : null;
});
const holdingProfitAmount = computed(() => {
  if (holdingMarketValue.value === null || !props.stock?.avg_cost) return null;
  const quantity = Number(props.stock.quantity);
  const averageCost = Number(props.stock.avg_cost);
  return Number.isFinite(quantity) && Number.isFinite(averageCost)
    ? holdingMarketValue.value - quantity * averageCost
    : null;
});
const holdingProfitPct = computed(() => {
  const averageCost = Number(props.stock?.avg_cost);
  const lastPrice = props.quote?.last_price;
  if (!Number.isFinite(averageCost) || averageCost <= 0 || lastPrice === null || lastPrice === undefined || !Number.isFinite(lastPrice)) {
    return null;
  }
  return ((lastPrice - averageCost) / averageCost) * 100;
});

function formatNumber(value: number | null | undefined, maximumFractionDigits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return value.toLocaleString(undefined, { maximumFractionDigits });
}

function formatSigned(value: number | null | undefined, suffix = ''): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}${suffix}`;
}

function formatSignedMarketAmount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${sign}${getMarketCurrencySymbol(props.stock?.market_type)}${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function movementClass(value: number | null | undefined): string {
  if (value && value > 0) return 'text-red-500';
  if (value && value < 0) return 'text-emerald-500';
  return 'text-secondary-text';
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="stock"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="stock-detail-title"
      @click.self="$emit('close')"
    >
      <div class="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-border bg-card shadow-2xl">
        <header class="sticky top-0 z-10 flex items-start justify-between border-b border-border/70 bg-card px-6 py-5">
          <div>
            <div class="flex flex-wrap items-center gap-2">
              <h2 id="stock-detail-title" class="text-lg font-semibold text-foreground">{{ stock.name || stock.code }}</h2>
              <span class="font-mono text-sm font-semibold text-primary">{{ stock.code }}</span>
              <span class="rounded-lg border border-border/60 bg-background px-2 py-0.5 text-xs text-secondary-text">{{ marketName }}</span>
            </div>
            <p class="mt-1 text-xs text-muted-text">股票完整信息与每 5 秒更新的行情快照</p>
          </div>
          <button class="rounded-lg p-1.5 text-secondary-text hover:bg-hover hover:text-foreground" aria-label="关闭详情" @click="$emit('close')">
            <X class="h-5 w-5" />
          </button>
        </header>

        <div class="space-y-6 p-6">
          <section>
            <h3 class="mb-3 text-sm font-semibold text-foreground">实时行情</h3>
            <div v-if="quote?.available" class="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div class="col-span-2 rounded-xl border border-border/60 bg-background p-4 sm:col-span-1">
                <p class="text-xs text-muted-text">最新价</p>
                <p class="mt-1 text-xl font-semibold tabular-nums text-foreground">{{ formatNumber(quote.last_price, 4) }}</p>
              </div>
              <div class="rounded-xl border border-border/60 bg-background p-4">
                <p class="text-xs text-muted-text">今日涨跌额</p>
                <p class="mt-1 text-base font-semibold tabular-nums" :class="movementClass(quote.change_amount)">{{ formatSigned(quote.change_amount) }}</p>
              </div>
              <div class="rounded-xl border border-border/60 bg-background p-4">
                <p class="text-xs text-muted-text">今日涨跌幅</p>
                <p class="mt-1 text-base font-semibold tabular-nums" :class="movementClass(quote.change_pct)">{{ formatSigned(quote.change_pct, '%') }}</p>
              </div>
              <div class="rounded-xl border border-border/60 bg-background p-4">
                <p class="text-xs text-muted-text">交易时段</p>
                <p class="mt-1 text-sm font-medium text-foreground">{{ quote.trade_session || '—' }}</p>
              </div>
            </div>
            <p v-else class="rounded-xl border border-dashed border-border/70 bg-background px-4 py-6 text-center text-sm text-muted-text">
              暂无该股票的实时行情
            </p>

            <dl class="mt-3 grid grid-cols-2 overflow-hidden rounded-xl border border-border/60 sm:grid-cols-4">
              <div v-for="entry in [
                ['行情标识', quote?.symbol || '—'],
                ['开盘', formatNumber(quote?.open, 4)],
                ['最高', formatNumber(quote?.high, 4)],
                ['最低', formatNumber(quote?.low, 4)],
                ['昨收', formatNumber(quote?.pre_close, 4)],
                ['成交量 (Volume)', formatNumber(quote?.volume, 0)],
                ['成交额', formatNumber(quote?.turnover, 2)],
                ['行情时间', formatDateTimeInDisplayTimezone(quote?.event_time)],
                ['接收时间', formatDateTimeInDisplayTimezone(quote?.received_at)],
              ]" :key="entry[0]" class="min-w-0 border-b border-r border-border/50 p-3 last:border-r-0">
                <dt class="whitespace-nowrap text-xs text-muted-text">{{ entry[0] }}</dt>
                <dd class="mt-1 truncate text-sm tabular-nums text-foreground" :title="entry[1]">{{ entry[1] }}</dd>
              </div>
            </dl>
          </section>

          <section>
            <h3 class="mb-3 text-sm font-semibold text-foreground">{{ kind === 'holding' ? '持仓信息' : '自选信息' }}</h3>
            <dl class="grid grid-cols-1 gap-x-8 gap-y-4 rounded-xl border border-border/60 bg-background p-4 sm:grid-cols-2">
              <div><dt class="text-xs text-muted-text">股票代码</dt><dd class="mt-1 font-mono text-sm text-foreground">{{ stock.code }}</dd></div>
              <div><dt class="text-xs text-muted-text">股票名称</dt><dd class="mt-1 text-sm text-foreground">{{ stock.name || '—' }}</dd></div>
              <div><dt class="text-xs text-muted-text">所属市场</dt><dd class="mt-1 text-sm text-foreground">{{ marketName }}</dd></div>
              <div><dt class="text-xs text-muted-text">计价币种</dt><dd class="mt-1 text-sm text-foreground">{{ currencyCode }}</dd></div>
              <template v-if="kind === 'holding'">
                <div><dt class="text-xs text-muted-text">持仓数量</dt><dd class="mt-1 text-sm text-foreground">{{ formatDecimalText(stock.quantity) }} 股</dd></div>
                <div><dt class="text-xs text-muted-text">平均成本</dt><dd class="mt-1 text-sm text-foreground">{{ formatMarketCurrencyAmount(stock.avg_cost, stock.market_type) }}</dd></div>
                <div><dt class="text-xs text-muted-text">持仓成本金额</dt><dd class="mt-1 text-sm text-foreground">{{ formatHoldingCostAmount(stock.quantity, stock.avg_cost, stock.market_type) }}</dd></div>
                <div><dt class="text-xs text-muted-text">最新市值</dt><dd class="mt-1 text-sm text-foreground">{{ formatMarketCurrencyAmount(holdingMarketValue, stock.market_type) }}</dd></div>
                <div><dt class="text-xs text-muted-text">浮动盈亏</dt><dd class="mt-1 text-sm font-medium" :class="movementClass(holdingProfitAmount)">{{ formatSignedMarketAmount(holdingProfitAmount) }}</dd></div>
                <div><dt class="text-xs text-muted-text">持仓收益率</dt><dd class="mt-1 text-sm font-medium" :class="movementClass(holdingProfitPct)">{{ formatSigned(holdingProfitPct, '%') }}</dd></div>
                <div><dt class="text-xs text-muted-text">首次建仓时间</dt><dd class="mt-1 text-sm text-foreground">{{ formatDateTimeInDisplayTimezone(stock.opened_at) }}</dd></div>
              </template>
              <div v-else><dt class="text-xs text-muted-text">特别关注</dt><dd class="mt-1 text-sm text-foreground">{{ stock.is_favorite ? '是' : '否' }}</dd></div>
              <div class="sm:col-span-2"><dt class="text-xs text-muted-text">备注</dt><dd class="mt-1 whitespace-pre-wrap break-words text-sm text-foreground">{{ stock.notes || '—' }}</dd></div>
              <div><dt class="text-xs text-muted-text">记录 ID</dt><dd class="mt-1 font-mono text-sm text-foreground">{{ stock.id }}</dd></div>
              <div><dt class="text-xs text-muted-text">添加时间</dt><dd class="mt-1 text-sm text-foreground">{{ formatDateTimeInDisplayTimezone(stock.created_at) }}</dd></div>
              <div><dt class="text-xs text-muted-text">更新时间</dt><dd class="mt-1 text-sm text-foreground">{{ formatDateTimeInDisplayTimezone(stock.updated_at) }}</dd></div>
            </dl>
          </section>
        </div>
      </div>
    </div>
  </Teleport>
</template>
