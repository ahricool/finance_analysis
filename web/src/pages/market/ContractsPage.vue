<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { Search, Trash2 } from 'lucide-vue-next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { contractsApi, type Candle, type Contract, type ContractQuote, type MarketSnapshot } from '@/api/contracts';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import MarketKLineChart from '@/components/market-data/MarketKLineChart.vue';
import { useTableSort, sortField } from '@/composables/useTableSort';
import { useContractMarket } from '@/composables/useContractMarket';
import { useAuthStore } from '@/stores/authStore';
import { useCurrentTime } from '@/composables/useCurrentTime';

const rows = ref<ContractQuote[]>([]);
const symbol = ref('');
const interval = ref<'1d' | '1m'>('1d');
const minutes = ref<Candle[]>([]);
const daily = ref<Candle[]>([]);
const current = ref<Candle | null>(null);
const loadingDaily = ref(false);
const received = ref(false);
const error = ref<ParsedApiError | null>(null);
const query = ref('');
const results = ref<Contract[]>([]);
const searching = ref(false);
const searched = ref(false);
const busy = ref(false);
const removing = ref('');
const auth = useAuthStore();
const admin = computed(() => auth.currentUser?.role === 'admin');
const now = useCurrentTime(5_000);
const sort = useTableSort(() => rows.value, (row, key) => sortField(row, key));
const selection = computed(() => rows.value.find(row => row.symbol === symbol.value));
const columns = [
  { key: 'symbol', label: '合约' }, { key: 'category', label: '分类' },
  { key: 'quote.price', label: '最新价' }, { key: 'quote.change_pct', label: '24h 涨跌幅' },
  { key: 'quote.turnover', label: '24h 成交额' }, { key: 'quote.funding_rate', label: '资金费率' },
];
const chartBars = computed(() => interval.value === '1m' ? minutes.value :
  daily.value.filter(bar => bar.timestamp !== current.value?.timestamp));
const chartCurrent = computed(() => interval.value === '1d' ? current.value : null);
const minuteTimestamp = computed(() => minutes.value.at(-1)?.timestamp);
const minuteDelayed = computed(() => minuteTimestamp.value != null && now.value.getTime() - minuteTimestamp.value > 120_000);
const precision = computed(() => {
  const price = selection.value?.quote?.price ?? chartBars.value.at(-1)?.close ?? 1;
  return price >= 100 ? 2 : Math.max(2, Math.min(10, 3 - Math.floor(Math.log10(price))));
});
let generation = 0;
let searchGeneration = 0;
let lastDailyRead = 0;
let stopped = false;
async function loadDaily() {
  if (!symbol.value) return;
  const version = ++generation;
  const selected = symbol.value;
  loadingDaily.value = true;
  lastDailyRead = Date.now();
  try {
    const bars = await contractsApi.bars(selected);
    if (!stopped && version === generation) daily.value = bars;
  } catch (err) {
    if (!stopped && version === generation) error.value = getParsedApiError(err);
  } finally {
    if (version === generation) loadingDaily.value = false;
  }
}
watch(symbol, () => {
  ++generation;
  daily.value = [];
  minutes.value = [];
  current.value = null;
  loadingDaily.value = false;
  void loadDaily();
});
function receive(snapshot: MarketSnapshot) {
  received.value = true;
  rows.value = snapshot.items;
  if (!rows.value.some(row => row.symbol === symbol.value)) {
    symbol.value = rows.value[0]?.symbol ?? '';
    return;
  }
  if (snapshot.symbol !== symbol.value) return;
  if (interval.value === '1m') minutes.value = snapshot.minutes ?? [];
  else current.value = snapshot.daily_current;
  if (interval.value === '1d' && Date.now() - lastDailyRead >= 60_000 && !loadingDaily.value) void loadDaily();
}
const { status } = useContractMarket(symbol, interval, receive)
void contractsApi.snapshot().then(snapshot => {
  if (!stopped && !received.value) receive(snapshot);
}).catch(err => {
  if (!stopped && !received.value) error.value = getParsedApiError(err);
});;
watch(query, () => { ++searchGeneration; searching.value = false; searched.value = false; results.value = []; });
async function search() {
  const q = query.value.trim();
  if (!q) return;
  const version = ++searchGeneration;
  searching.value = true;
  searched.value = false;
  results.value = [];
  error.value = null;
  try {
    const found = await contractsApi.search(q);
    if (!stopped && version === searchGeneration) { results.value = found; searched.value = true; }
  } catch (err) {
    if (!stopped && version === searchGeneration) error.value = getParsedApiError(err);
  } finally {
    if (version === searchGeneration) searching.value = false;
  }
}
async function add(item: Contract) {
  busy.value = true;
  error.value = null;
  try {
    const saved = await contractsApi.add(item);
    if (!stopped) {
      if (!rows.value.some(row => row.symbol === saved.symbol)) rows.value.push({ ...saved, quote: null });
      symbol.value = saved.symbol;
      query.value = '';
    }
  } catch (err) { if (!stopped) error.value = getParsedApiError(err); }
  finally { busy.value = false; }
}
async function remove() {
  const target = removing.value;
  removing.value = '';
  if (!target) return;
  busy.value = true;
  error.value = null;
  try {
    await contractsApi.remove(target);
    if (!stopped) {
      rows.value = rows.value.filter(row => row.symbol !== target);
      if (symbol.value === target) symbol.value = rows.value[0]?.symbol ?? '';
    }
  } catch (err) { if (!stopped) error.value = getParsedApiError(err); }
  finally { busy.value = false; }
}
function format(value: number | null | undefined, digits = 2) {
  return value == null ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: digits });
}
function percent(value: number | null | undefined, digits = 2) {
  return value == null ? '—' : (value > 0 ? '+' : '') + value.toFixed(digits) + '%';
}
function categoryLabel(category: string) {
  return ({ COIN: '加密货币', EQUITY: '股票/ETF', KR_EQUITY: '韩股', COMMODITY: '商品' } as Record<string, string>)[category] ?? category;
}
function delayed(row: ContractQuote) {
  return !row.quote || Math.abs(now.value.getTime() - row.quote.timestamp) > 60_000;
}
onBeforeUnmount(() => { stopped = true; ++generation; ++searchGeneration; });
</script>

<template>
  <div
    class="space-y-5 py-6"
    data-testid="contracts-page"
  >
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-3xl font-semibold tracking-tight">
          合约行情
        </h1>
        <p class="mt-1 text-sm text-muted-foreground">
          USDⓈ-M Perpetual · USDT 本位永续 · Binance
        </p>
      </div>
      <span
        class="rounded-md border px-3 py-1.5 text-xs text-muted-foreground"
        role="status"
      >{{ status }}</span>
    </header>

    <AppApiErrorAlert
      v-if="error"
      :error="error"
      @dismiss="error = null"
    />
    <section
      v-if="admin"
      class="space-y-3 rounded-lg border p-4"
    >
      <form
        class="flex flex-wrap items-center gap-2"
        @submit.prevent="search"
      >
        <Input
          v-model="query"
          class="w-full sm:w-72"
          placeholder="搜索 USDT 永续合约代码"
          aria-label="搜索合约"
        />
        <Button
          type="submit"
          variant="outline"
          :disabled="searching || !query.trim()"
        >
          <Search class="size-4" /> {{ searching ? '搜索中' : '搜索' }}
        </Button>
      </form>
      <div
        v-if="results.length"
        class="flex flex-wrap gap-2"
      >
        <Button
          v-for="item in results"
          :key="item.symbol"
          size="sm"
          variant="outline"
          :disabled="busy || rows.some(row => row.symbol === item.symbol)"
          @click="add(item)"
        >
          {{ item.symbol }} · {{ rows.some(row => row.symbol === item.symbol) ? '已添加' : '添加' }}
        </Button>
      </div>
      <p
        v-else-if="searched"
        class="text-sm text-muted-foreground"
      >
        未找到交易中的 USDT 永续合约。
      </p>
    </section>

    <section class="min-w-0 rounded-lg border p-4">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-lg font-semibold">
            {{ symbol || '选择合约' }}
          </h2>
          <p class="text-sm tabular-nums text-muted-foreground">
            {{ selection ? categoryLabel(selection.category) : '' }} · {{ format(selection?.quote?.price, precision) }} USDT
          </p>
        </div>
        <div class="flex gap-2">
          <Button
            :variant="interval === '1d' ? 'default' : 'outline'"
            size="sm"
            @click="interval = '1d'"
          >
            日 K
          </Button>
          <Button
            :variant="interval === '1m' ? 'default' : 'outline'"
            size="sm"
            @click="interval = '1m'"
          >
            1 分钟 K
          </Button>
        </div>
      </div>
      <p class="mb-2 text-xs text-muted-foreground">
        {{ interval === '1m' ? '最近 24 小时 · 原生 1 分钟 K 线' : 'UTC 日线 · 已收盘历史来自数据库，当日为实时预览' }}
        <span v-if="interval === '1m' && minuteDelayed"> · 最新分钟线停留在 {{ new Date(minuteTimestamp!).toISOString().slice(0, 16).replace('T', ' ') }} UTC</span>
      </p>
      <MarketKLineChart
        v-if="symbol && (chartBars.length || chartCurrent)"
        :key="symbol + interval"
        :symbol="symbol"
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
        class="flex min-h-72 items-center justify-center text-sm text-muted-foreground"
      >
        {{ !received || (interval === '1d' && loadingDaily) ? '行情加载中…' : '暂无 K 线，等待后台采集' }}
      </div>
    </section>

    <section class="rounded-lg border">
      <div class="flex items-center justify-between border-b px-4 py-3">
        <h2 class="font-semibold">
          合约列表 <span class="text-xs text-muted-foreground"> {{ rows.length }} 个</span>
        </h2>
        <span class="text-xs text-muted-foreground">24h 成交额：USDT</span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b">
              <SortableTableHeader
                v-for="column in columns"
                :key="column.key"
                :label="column.label"
                :align="column.key.startsWith('quote.') ? 'right' : 'left'"
                v-bind="sort.header(column.key)"
              />
              <th
                v-if="admin"
                class="px-4 text-right"
              >
                操作
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in sort.sorted"
              :key="row.symbol"
              class="border-b last:border-0 hover:bg-muted/40"
              :class="row.symbol === symbol ? 'bg-muted/60' : ''"
            >
              <td class="whitespace-nowrap px-4 py-3">
                <button
                  class="font-semibold text-foreground hover:underline"
                  type="button"
                  :aria-pressed="row.symbol === symbol"
                  @click="symbol = row.symbol"
                >
                  {{ row.symbol }}
                </button>
                <span
                  v-if="delayed(row)"
                  class="ml-2 text-xs text-muted-foreground"
                >{{ row.quote ? '延迟' : '暂无行情' }}</span>
              </td>
              <td class="whitespace-nowrap px-4 py-3 text-muted-foreground">
                {{ categoryLabel(row.category) }}
              </td>
              <td class="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                {{ format(row.quote?.price, 10) }}
              </td>
              <td
                class="whitespace-nowrap px-4 py-3 text-right tabular-nums"
                :class="row.quote && row.quote.change_pct !== 0 ? row.quote.change_pct > 0 ? 'text-[var(--market-up)]' : 'text-[var(--market-down)]' : ''"
              >
                {{ percent(row.quote?.change_pct) }}
              </td>
              <td class="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                {{ format(row.quote?.turnover, 0) }}
              </td>
              <td class="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                {{ percent(row.quote?.funding_rate == null ? null : row.quote.funding_rate * 100, 4) }}
              </td>
              <td
                v-if="admin"
                class="px-4 py-2 text-right"
              >
                <Button
                  variant="ghost"
                  size="icon-sm"
                  :aria-label="'移除 ' + row.symbol"
                  :disabled="busy"
                  @click="removing = row.symbol"
                >
                  <Trash2 class="size-4" />
                </Button>
              </td>
            </tr>
          </tbody>
        </table>
        <p
          v-if="!rows.length"
          class="p-8 text-center text-sm text-muted-foreground"
        >
          {{ received ? '暂无标的' : '正在连接行情…' }}
        </p>
      </div>
    </section>

    <AppConfirmDialog
      :open="!!removing"
      title="移除合约"
      :description="'移除 ' + removing + ' 及其已保存日线？'"
      destructive
      @update:open="value => { if (!value) removing = '' }"
      @confirm="remove"
    />
  </div>
</template>
