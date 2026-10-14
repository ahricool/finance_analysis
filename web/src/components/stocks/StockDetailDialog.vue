<script setup lang="ts">
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import ResearchEvidence from './ResearchEvidence.vue';
import StockIndustryTags from './StockIndustryTags.vue';
import type { RealtimeQuote } from '@/api/realtimeMarket';
import type { MarketType } from '@/api/watchList';
import { stocksApi } from '@/api/stocks';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import { formatSecurityLabel } from '@/utils/security';
import { signedTextClass } from '@/utils/marketTone';
import {
  formatDecimalText,
  formatHoldingCostAmount,
  formatMarketCurrencyAmount,
  getMarketCurrencyCode,
  getMarketCurrencySymbol,
} from '@/utils/marketCurrency';
import { computed, defineAsyncComponent, onBeforeUnmount, ref, watch } from 'vue';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { OptionsView } from '@/api/optionsIntelligence';
import type { StockDetailContext, StockDetailTab } from './detail/types';

const HoldingsDetailPanel = defineAsyncComponent(() => import('./detail/HoldingsDetailPanel.vue'));
const DailyKLineCard = defineAsyncComponent(() => import('@/components/market-data/DailyKLineCard.vue'));
const OptionsPanel = defineAsyncComponent(() => import('@/components/options-intelligence/OptionsPanel.vue'));
const detailPanels = {
  trend: defineAsyncComponent(() => import('./detail/TrendDetailPanel.vue')),
  etf: defineAsyncComponent(() => import('./detail/ETFDetailPanel.vue')),
  confluence: defineAsyncComponent(() => import('./detail/ConfluenceDetailPanel.vue')),
  intraday: defineAsyncComponent(() => import('./detail/IntradayDetailPanel.vue')),
  'dragon-tiger': defineAsyncComponent(() => import('./detail/DragonTigerDetailPanel.vue')),
  quant: defineAsyncComponent(() => import('./detail/QuantDetailPanel.vue')),
};

export interface StockDetailRecord {
  id?: number;
  code: string;
  name: string | null;
  market_type: MarketType;
  notes?: string | null;
  is_favorite?: boolean;
  quantity?: string;
  avg_cost?: string | null;
  opened_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

const props = withDefaults(defineProps<{
  open?: boolean;
  stock: StockDetailRecord | null;
  quote?: RealtimeQuote;
  kind: 'watchlist' | 'holding' | 'research';
  initialTab?: StockDetailTab;
  context?: StockDetailContext;
  optionsView?: OptionsView;
  optionsDate?: string;
}>(), { open: undefined, quote: undefined, initialTab: 'overview', context: undefined, optionsView: undefined, optionsDate: undefined });
const emit = defineEmits<{ 'update:open': [value: boolean]; 'holdings-updated': [] }>();

const isOpen = computed(() => props.open ?? Boolean(props.stock));
const tabs = computed<Array<{ value: StockDetailTab; label: string }>>(() => [
  { value: 'overview', label: '行情' },
  { value: 'holdings', label: '持仓' },
  ...(props.stock?.market_type === 'US' ? [{ value: 'options' as const, label: '期权' }] : []),
  ...(props.stock?.market_type !== 'HK' ? [
    { value: 'trend' as const, label: '趋势' },
    { value: 'etf' as const, label: 'ETF 轮动' },
    { value: 'confluence' as const, label: '共振' },
    { value: 'intraday' as const, label: '盘中确认' },
    { value: 'quant' as const, label: '量化' },
  ] : []),
  ...(props.stock?.market_type === 'CN' ? [{ value: 'dragon-tiger' as const, label: '龙虎榜' }] : []),
]);
const activeTab = ref<StockDetailTab>('overview');
const detailContext = computed<StockDetailContext>(() => ({
  ...props.context,
  view: props.context?.view ?? props.optionsView,
  tradeDate: props.context?.tradeDate ?? props.optionsDate,
}));
const contextKey = computed(() => JSON.stringify(detailContext.value));
const panelKey = computed(() => `${props.stock?.market_type}:${props.stock?.code}:${contextKey.value}:${activeTab.value}`);
const activePanel = computed(() => activeTab.value in detailPanels
  ? detailPanels[activeTab.value as keyof typeof detailPanels] : null);
watch(
  [() => isOpen.value, () => props.stock?.code, () => props.stock?.market_type, () => props.initialTab, () => contextKey.value, () => props.optionsView, () => props.optionsDate],
  () => { activeTab.value = tabs.value.some(tab => tab.value === props.initialTab) ? props.initialTab! : 'overview'; },
  { immediate: true },
);

const fetchedQuote = ref<RealtimeQuote>();
const quoteLoading = ref(false);
const quoteError = ref<ParsedApiError | null>(null);
const suppliedQuote = computed(() => props.stock && props.quote
  && props.quote.market_type === props.stock.market_type
  && [props.quote.code, props.quote.symbol].some(code => code.trim().toUpperCase() === props.stock!.code.trim().toUpperCase())
  ? props.quote : undefined);
const displayQuote = computed(() => suppliedQuote.value ?? fetchedQuote.value);
let quoteRequest = 0;
let quoteController: AbortController | undefined;
async function loadQuote() {
  const request = ++quoteRequest;
  quoteController?.abort();
  fetchedQuote.value = undefined; quoteError.value = null; quoteLoading.value = false;
  if (!isOpen.value || activeTab.value !== 'overview' || !props.stock || suppliedQuote.value) return;
  const { code, market_type: market } = props.stock;
  const controller = new AbortController();
  quoteController = controller; quoteLoading.value = true;
  try {
    const result = await stocksApi.quote(code, market, controller.signal);
    if (request === quoteRequest && !controller.signal.aborted
      && [result.code, result.symbol].some(value => value.trim().toUpperCase() === code.trim().toUpperCase())) fetchedQuote.value = result;
  } catch (err) {
    if (request === quoteRequest && !controller.signal.aborted) {
      const parsed = getParsedApiError(err);
      if (parsed.status !== 404) quoteError.value = parsed;
    }
  } finally {
    if (request === quoteRequest) quoteLoading.value = false;
  }
}
watch([isOpen, activeTab, () => props.stock?.code, () => props.stock?.market_type, suppliedQuote], loadQuote, { immediate: true });
onBeforeUnmount(() => { quoteRequest++; quoteController?.abort(); });

const marketName = computed(
  () => ({ CN: 'A 股', HK: '港股', US: '美股' })[props.stock?.market_type ?? 'CN'],
);
const currencyCode = computed(() => getMarketCurrencyCode(props.stock?.market_type));
const holdingMarketValue = computed(() => {
  if (props.kind !== 'holding' || !displayQuote.value?.available) return null;
  const quantity = Number(props.stock?.quantity);
  const lastPrice = displayQuote.value!.last_price;
  return Number.isFinite(quantity) &&
    lastPrice !== null &&
    lastPrice !== undefined &&
    Number.isFinite(lastPrice)
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
  const lastPrice = displayQuote.value?.last_price;
  if (
    !Number.isFinite(averageCost) ||
    averageCost <= 0 ||
    lastPrice === null ||
    lastPrice === undefined ||
    !Number.isFinite(lastPrice)
  ) {
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
  return `${sign}${getMarketCurrencySymbol(props.stock?.market_type)}${Math.abs(
    value,
  ).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function movementClass(value: number | null | undefined): string {
  return signedTextClass(value);
}
</script>

<template>
  <Dialog
    :open="isOpen"
    @update:open="emit('update:open', $event)"
  >
    <DialogContent class="flex max-h-[calc(100dvh-2rem)] min-w-0 flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl">
      <DialogHeader class="shrink-0 p-6 pr-16 text-left">
        <DialogTitle class="flex flex-wrap items-center gap-2 break-words">
          {{ formatSecurityLabel(stock?.code, stock?.name, '股票详情') }}
          <span
            class="rounded-lg border border-border/60 bg-background px-2 py-0.5 text-xs text-muted-foreground"
          >{{ marketName }}</span>
        </DialogTitle>
        <DialogDescription>查看同一股票或 ETF 的行情、持仓与研究详情；各页签保留各自的数据日期与口径。</DialogDescription>
        <StockIndustryTags
          v-if="stock?.market_type === 'CN' && isOpen"
          :key="stock.code"
          :code="stock.code"
        />
      </DialogHeader>
      <Tabs
        v-model="activeTab"
        class="flex min-h-0 min-w-0 flex-1 flex-col gap-0"
      >
        <div class="shrink-0 overflow-x-auto px-4 pb-3 sm:px-6">
          <TabsList
            data-testid="stock-detail-tabs"
            class="w-max min-w-full justify-start"
          >
            <TabsTrigger
              v-for="tab in tabs"
              :key="tab.value"
              :value="tab.value"
              class="shrink-0"
            >
              {{ tab.label }}
            </TabsTrigger>
          </TabsList>
        </div>
        <Separator />
        <TabsContent
          v-if="stock && isOpen"
          :key="panelKey"
          :value="activeTab"
          class="m-0 w-full min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]"
        >
          <HoldingsDetailPanel
            v-if="activeTab === 'holdings'"
            :symbol="stock.code"
            :market="stock.market_type"
            :context="detailContext"
            class="p-4 sm:p-6"
            @updated="emit('holdings-updated')"
          />
          <component
            :is="activePanel"
            v-else-if="activePanel"
            :symbol="stock.code"
            :market="stock.market_type"
            :context="detailContext"
            class="p-4 sm:p-6"
          />
          <OptionsPanel
            v-else-if="activeTab === 'options' && stock.market_type === 'US'"
            :key="stock.code"
            :symbol="stock.code"
            :initial-view="optionsView ?? context?.view"
            :initial-date="optionsDate ?? context?.tradeDate"
            class="p-6"
          />
          <div
            v-else
            class="space-y-6 p-6"
          >
            <section>
              <h3 class="mb-3 text-sm font-semibold text-foreground">
                实时行情
              </h3>
              <p
                v-if="quoteLoading"
                role="status"
                class="text-sm text-muted-foreground"
              >
                正在加载行情…
              </p>
              <AppApiErrorAlert
                v-else-if="quoteError"
                :error="quoteError"
                action-label="重试行情"
                @action="loadQuote"
              />
              <dl
                v-else-if="displayQuote?.available"
                class="grid grid-cols-2 gap-3"
              >
                <div
                  v-for="metric in [
                    { label: '最新价', value: formatNumber(displayQuote.last_price, 4) },
                    { label: '今日涨跌额', value: formatSigned(displayQuote.change_amount), color: movementClass(displayQuote.change_amount) },
                    { label: '今日涨跌幅', value: formatSigned(displayQuote.change_pct, '%'), color: movementClass(displayQuote.change_pct) },
                    { label: '交易时段', value: displayQuote.trade_session || '—' },
                  ]"
                  :key="metric.label"
                  class="min-w-0 rounded-xl border border-border/60 bg-background p-4"
                >
                  <dt class="text-sm text-muted-foreground">
                    <IndicatorHelpLabel
                      scope="watch"
                      :label="metric.label"
                      compact
                    />
                  </dt>
                  <dd
                    class="mt-2 break-words text-xl font-semibold tabular-nums"
                    :class="metric.color"
                  >
                    {{ metric.value }}
                  </dd>
                </div>
              </dl>
              <p
                v-else
                class="rounded-xl border border-dashed border-border/70 bg-background px-4 py-6 text-center text-sm text-muted-foreground"
              >
                暂无该股票的实时行情
              </p>

              <Button
                v-if="!suppliedQuote && !quoteLoading && !quoteError"
                variant="outline"
                size="sm"
                class="mt-3"
                @click="loadQuote"
              >
                刷新行情
              </Button>
              <dl
                class="mt-3 grid grid-cols-2 overflow-hidden rounded-xl border border-border/60"
              >
                <div
                  v-for="entry in [
                    ['行情标识', formatSecurityLabel(displayQuote?.symbol, stock.name)],
                    ['开盘', formatNumber(displayQuote?.open, 4)],
                    ['最高', formatNumber(displayQuote?.high, 4)],
                    ['最低', formatNumber(displayQuote?.low, 4)],
                    ['昨收', formatNumber(displayQuote?.pre_close, 4)],
                    ['成交量 (Volume)', formatNumber(displayQuote?.volume, 0)],
                    ['成交额', formatNumber(displayQuote?.turnover, 2)],
                    ['行情时间', formatDateTimeInDisplayTimezone(displayQuote?.event_time)],
                    ['接收时间', formatDateTimeInDisplayTimezone(displayQuote?.received_at)],
                  ]"
                  :key="entry[0]"
                  class="min-w-0 border-b border-border/50 p-4"
                  :class="['行情标识', '行情时间', '接收时间'].includes(entry[0] ?? '') ? 'col-span-2' : ''"
                >
                  <dt class="text-xs leading-5 text-muted-foreground">
                    <IndicatorHelpLabel
                      scope="watch"
                      :label="entry[0]!"
                      compact
                    />
                  </dt>
                  <dd
                    class="mt-1 break-words text-sm leading-6 tabular-nums text-foreground"
                  >
                    {{ entry[1] }}
                  </dd>
                </div>
              </dl>
            </section>

            <DailyKLineCard
              :symbol="stock.code"
              :highlight-date="detailContext.tradeDate"
            />
            <ResearchEvidence
              :key="stock.code"
              :symbol="stock.code"
              :market="stock.market_type"
            />

            <section v-if="kind !== 'research'">
              <h3 class="mb-3 text-sm font-semibold text-foreground">
                {{ kind === 'holding' ? '持仓信息' : '自选信息' }}
              </h3>
              <dl
                class="grid grid-cols-2 gap-x-8 gap-y-4 rounded-xl border border-border/60 bg-background p-4 [&>div]:min-w-0 [&_dd]:break-words"
              >
                <div class="col-span-2">
                  <dt class="text-xs text-muted-foreground">
                    <IndicatorHelpLabel
                      scope="watch"
                      label="股票"
                      compact
                    />
                  </dt>
                  <dd class="mt-1 text-sm text-foreground">
                    {{ formatSecurityLabel(stock.code, stock.name) }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    <IndicatorHelpLabel
                      scope="watch"
                      label="所属市场"
                      compact
                    />
                  </dt>
                  <dd class="mt-1 text-sm text-foreground">
                    {{ marketName }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    <IndicatorHelpLabel
                      scope="watch"
                      label="计价币种"
                      compact
                    />
                  </dt>
                  <dd class="mt-1 text-sm text-foreground">
                    {{ currencyCode }}
                  </dd>
                </div>
                <template v-if="kind === 'holding'">
                  <div>
                    <dt class="text-xs text-muted-foreground">
                      <IndicatorHelpLabel
                        scope="watch"
                        label="持仓数量"
                        compact
                      />
                    </dt>
                    <dd class="mt-1 text-sm text-foreground">
                      {{ formatDecimalText(stock.quantity) }} 股
                    </dd>
                  </div>
                  <div>
                    <dt class="text-xs text-muted-foreground">
                      <IndicatorHelpLabel
                        scope="watch"
                        label="平均成本"
                        compact
                      />
                    </dt>
                    <dd class="mt-1 text-sm text-foreground">
                      {{ formatMarketCurrencyAmount(stock.avg_cost, stock.market_type) }}
                    </dd>
                  </div>
                  <div>
                    <dt class="text-xs text-muted-foreground">
                      <IndicatorHelpLabel
                        scope="watch"
                        label="持仓成本金额"
                        compact
                      />
                    </dt>
                    <dd class="mt-1 text-sm text-foreground">
                      {{ formatHoldingCostAmount(stock.quantity, stock.avg_cost, stock.market_type) }}
                    </dd>
                  </div>
                  <div>
                    <dt class="text-xs text-muted-foreground">
                      <IndicatorHelpLabel
                        scope="watch"
                        label="最新市值"
                        compact
                      />
                    </dt>
                    <dd class="mt-1 text-sm text-foreground">
                      {{ formatMarketCurrencyAmount(holdingMarketValue, stock.market_type) }}
                    </dd>
                  </div>
                  <div>
                    <dt class="text-xs text-muted-foreground">
                      <IndicatorHelpLabel
                        scope="watch"
                        label="浮动盈亏"
                        compact
                      />
                    </dt>
                    <dd
                      class="mt-1 text-sm font-medium"
                      :class="movementClass(holdingProfitAmount)"
                    >
                      {{ formatSignedMarketAmount(holdingProfitAmount) }}
                    </dd>
                  </div>
                  <div>
                    <dt class="text-xs text-muted-foreground">
                      <IndicatorHelpLabel
                        scope="watch"
                        label="持仓收益率"
                        compact
                      />
                    </dt>
                    <dd
                      class="mt-1 text-sm font-medium"
                      :class="movementClass(holdingProfitPct)"
                    >
                      {{ formatSigned(holdingProfitPct, '%') }}
                    </dd>
                  </div>
                  <div>
                    <dt class="text-xs text-muted-foreground">
                      <IndicatorHelpLabel
                        scope="watch"
                        label="首次建仓时间"
                        compact
                      />
                    </dt>
                    <dd class="mt-1 text-sm text-foreground">
                      {{ formatDateTimeInDisplayTimezone(stock.opened_at) }}
                    </dd>
                  </div>
                </template>
                <div v-else>
                  <dt class="text-xs text-muted-foreground">
                    <IndicatorHelpLabel
                      scope="watch"
                      label="特别关注"
                      compact
                    />
                  </dt>
                  <dd class="mt-1 text-sm text-foreground">
                    {{ stock.is_favorite ? '是' : '否' }}
                  </dd>
                </div>
                <div class="col-span-2">
                  <dt class="text-xs text-muted-foreground">
                    <IndicatorHelpLabel
                      scope="watch"
                      label="备注"
                      compact
                    />
                  </dt>
                  <dd class="mt-1 whitespace-pre-wrap break-words text-sm text-foreground">
                    {{ stock.notes || '—' }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    <IndicatorHelpLabel
                      scope="watch"
                      label="记录 ID"
                      compact
                    />
                  </dt>
                  <dd class="mt-1 font-mono text-sm text-foreground">
                    {{ stock.id }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    <IndicatorHelpLabel
                      scope="watch"
                      label="添加时间"
                      compact
                    />
                  </dt>
                  <dd class="mt-1 text-sm text-foreground">
                    {{ formatDateTimeInDisplayTimezone(stock.created_at) }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    <IndicatorHelpLabel
                      scope="watch"
                      label="更新时间"
                      compact
                    />
                  </dt>
                  <dd class="mt-1 text-sm text-foreground">
                    {{ formatDateTimeInDisplayTimezone(stock.updated_at) }}
                  </dd>
                </div>
              </dl>
            </section>
          </div>
        </TabsContent>
      </Tabs>
    </DialogContent>
  </Dialog>
</template>
