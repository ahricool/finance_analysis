<script setup lang="ts">
import TrendWindowCell from '@/components/market-data/TrendWindowCell.vue';
import TrendDirectionCell from '@/components/market-data/TrendDirectionCell.vue';
import { opportunityKinds, stages, fmt } from '@/components/intraday-options/labels';
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { ChevronDown, ChevronRight, Plus, Trash2 } from 'lucide-vue-next';
import { Button } from '@/components/ui/button';
import { Table, TableHeader, TableBody, TableRow, TableCell, TableHead } from '@/components/ui/table';
import { contractsApi, type Candle, type Contract, type ContractQuote, type MarketSnapshot } from '@/api/contracts';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import ContractMarketPanel from '@/components/contracts/ContractMarketPanel.vue';
import ContractAddDialog from '@/components/contracts/ContractAddDialog.vue';
import { signedTextClass } from '@/utils/marketTone';
import { useTableSort, sortField } from '@/composables/useTableSort';
import { useContractMarket } from '@/composables/useContractMarket';
import { useAuthStore } from '@/stores/authStore';
import { useStockDetail } from '@/composables/useStockDetail';
import { useCurrentTime } from '@/composables/useCurrentTime';

const rows = ref<ContractQuote[]>([]);
const symbol = ref('');
const interval = ref<'1d' | '1m'>('1m');
const minutes = ref<Candle[]>([]);
const daily = ref<Candle[]>([]);
const current = ref<Candle | null>(null);
const loadingDaily = ref(false);
const received = ref(false);
const error = ref<ParsedApiError | null>(null);
const addOpen = ref(false);
const addError = ref<ParsedApiError | null>(null);
const chartError = ref<ParsedApiError | null>(null);
const chartReceived = ref(false);
const busy = ref(false);
const removing = ref('');
const auth = useAuthStore();
const detail = useStockDetail();
const admin = computed(() => auth.currentUser?.role === 'admin');
const now = useCurrentTime(5_000);
function currentOpportunity(row: ContractQuote) {
  const analysis = row.analysis;
  return analysis && !delayed(row) && status.value.endsWith('已连接') && now.value.getTime() - analysis.as_of < 90_000
    ? analysis.opportunity : null;
}
const sort = useTableSort(() => rows.value, (row, key) => {
  if (key === 'opportunity') return currentOpportunity(row)?.quality_score;
  if (key === 'direction') return currentOpportunity(row)?.direction ?? row.analysis?.direction;
  return sortField(row, key);
});
sort.sortKey = 'opportunity';
sort.direction = 'desc';
const existingSymbols = computed(() => rows.value.map(row => row.symbol));
const columns = [
  { key: 'symbol', label: '合约' }, { key: 'category', label: '分类' },
  { key: 'quote.price', label: '最新价' }, { key: 'quote.change_pct', label: '24h 涨跌幅' },
  { key: 'opportunity', label: '日内机会' }, { key: 'analysis.score', label: '趋势质量分' },
  { key: 'direction', label: '当前方向' }, { key: 'analysis.state', label: '当前状态' },
  ...[5, 15, 30, 60].map(n => ({ key: `analysis.windows.${n}.score`, label: `${n}分钟` })),
  { key: 'quote.turnover', label: '24h 成交额' }, { key: 'quote.funding_rate', label: '资金费率' },
];
const chartBars = computed(() => interval.value === '1m' ? minutes.value :
  daily.value.filter(bar => bar.timestamp !== current.value?.timestamp));
const chartCurrent = computed(() => interval.value === '1d' ? current.value : null);
let generation = 0;
let dailyRequest: AbortController | undefined;
let lastDailyRead = 0;
let stopped = false;
async function loadDaily() {
  if (!symbol.value || interval.value !== '1d' || loadingDaily.value) return;
  const version = ++generation;
  const selected = symbol.value;
  const request = new AbortController();
  dailyRequest = request;
  loadingDaily.value = true;
  chartError.value = null;
  lastDailyRead = Date.now();
  try {
    const bars = await contractsApi.bars(selected, request.signal);
    if (!stopped && version === generation) daily.value = bars;
  } catch (err) {
    if (!stopped && version === generation) chartError.value = getParsedApiError(err);
  } finally {
    if (version === generation) { dailyRequest = undefined; loadingDaily.value = false; }
  }
}
watch([symbol, interval], () => {
  ++generation;
  dailyRequest?.abort(); dailyRequest = undefined;
  daily.value = [];
  minutes.value = [];
  current.value = null;
  loadingDaily.value = false;
  chartReceived.value = false;
  chartError.value = null;
  if (symbol.value && interval.value === '1d') void loadDaily();
});
function receive(snapshot: MarketSnapshot) {
  if (!received.value) error.value = null;
  received.value = true;
  rows.value = snapshot.items;
  if (!symbol.value) return;
  if (!rows.value.some(row => row.symbol === symbol.value)) {
    symbol.value = '';
    return;
  }
  if (snapshot.symbol !== symbol.value) return;
  chartReceived.value = true;
  if (interval.value === '1m') minutes.value = snapshot.minutes ?? [];
  else current.value = snapshot.daily_current;
  if (interval.value === '1d' && Date.now() - lastDailyRead >= 60_000 && !loadingDaily.value) void loadDaily();
}
const { status, reconnect } = useContractMarket(symbol, interval, receive);
void contractsApi.snapshot().then(snapshot => {
  if (!stopped && !received.value) receive(snapshot);
}).catch(err => {
  if (!stopped && !received.value) error.value = getParsedApiError(err);
});
function toggleRow(target: string) {
  if (symbol.value === target) symbol.value = '';
  else {
    interval.value = '1m';
    symbol.value = target;
  }
}
function openAdd() { addError.value = null; addOpen.value = true; }
async function add(item: Contract) {
  if (busy.value) return;
  busy.value = true;
  addError.value = null;
  try {
    const saved = await contractsApi.add(item);
    if (!stopped) {
      if (!rows.value.some(row => row.symbol === saved.symbol)) rows.value = [...rows.value, { ...saved, quote: null }];
      received.value = true;
      reconnect();
    }
  } catch (err) { if (!stopped) addError.value = getParsedApiError(err); }
  finally { busy.value = false; }
}
async function remove() {
  const target = removing.value;
  removing.value = '';
  if (!target || busy.value) return;
  busy.value = true;
  error.value = null;
  try {
    await contractsApi.remove(target);
    if (!stopped) {
      rows.value = rows.value.filter(row => row.symbol !== target);
      received.value = true;
      if (symbol.value === target) symbol.value = '';
      else reconnect();
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
function openDetail(row: ContractQuote) {
  const target = row.underlying_symbol;
  const marketType = target?.endsWith('.US') ? 'US' : target?.endsWith('.HK') ? 'HK'
    : /\.(SH|SZ|BJ)$/.test(target ?? '') ? 'CN' : target?.endsWith('.CRYPTO') ? 'CRYPTO' : 'OTHER';
  detail.open({ code: target ?? row.symbol, name: null, marketType });
}
function underlyingLabel(row: ContractQuote) {
  return row.underlying_symbol?.replace(/\.(CRYPTO|OTHER)$/, '') ?? '锚定标的暂缺';
}
function delayed(row: ContractQuote) {
  return !row.quote || Math.abs(now.value.getTime() - row.quote.timestamp) > 60_000;
}
onBeforeUnmount(() => { stopped = true; ++generation; dailyRequest?.abort(); });
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
    <section class="rounded-lg border">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div>
          <h2 class="font-semibold">
            合约列表 <span class="text-xs text-muted-foreground"> {{ rows.length }} 个</span>
          </h2>
          <p class="text-xs text-muted-foreground">
            点击行展开行情，点击名称查看标的详情 · 成交额 USDT · 日内分析从 UTC 00:00 起使用已收盘分钟线
          </p>
        </div>
        <Button
          v-if="admin"
          :disabled="busy"
          @click="openAdd"
        >
          <Plus class="size-4" /> 添加合约
        </Button>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <SortableTableHeader
              v-for="column in columns"
              :key="column.key"
              :label="column.label"
              :align="column.key.startsWith('quote.') ? 'right' : 'left'"
              v-bind="sort.header(column.key)"
            />
            <TableHead
              v-if="admin"
              class="sticky right-0 z-10 bg-muted px-4 text-right"
            >
              操作
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <template
            v-for="row in sort.sorted"
            :key="row.symbol"
          >
            <TableRow
              data-testid="contract-row"
              class="cursor-pointer"
              :class="row.symbol === symbol ? 'bg-muted/60' : ''"
              tabindex="0"
              :aria-label="`展开 ${row.symbol} 合约行情`"
              :aria-expanded="row.symbol === symbol"
              @click="toggleRow(row.symbol)"
              @keydown.enter.self="toggleRow(row.symbol)"
              @keydown.space.self.prevent="toggleRow(row.symbol)"
            >
              <TableCell class="whitespace-nowrap px-4 py-3">
                <span class="inline-flex items-center gap-1.5">
                  <component
                    :is="row.symbol === symbol ? ChevronDown : ChevronRight"
                    class="size-4 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <button
                    class="rounded-sm font-semibold text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    type="button"
                    :aria-label="row.symbol + ' 标的详情'"
                    @click.stop="openDetail(row)"
                    @keydown.enter.stop
                    @keydown.space.stop
                  >
                    {{ row.symbol }}
                    <span class="ml-1 text-xs font-normal text-muted-foreground">{{ underlyingLabel(row) }}</span>
                  </button>
                </span>
                <span
                  v-if="delayed(row)"
                  class="ml-2 text-xs text-muted-foreground"
                >{{ row.quote ? '延迟' : '暂无行情' }}</span>
              </TableCell>
              <TableCell class="whitespace-nowrap px-4 py-3 text-muted-foreground">
                {{ categoryLabel(row.category) }}
              </TableCell>
              <TableCell class="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                {{ format(row.quote?.price, 10) }}
              </TableCell>
              <TableCell
                class="whitespace-nowrap px-4 py-3 text-right tabular-nums"
                :class="signedTextClass(row.quote?.change_pct)"
              >
                {{ percent(row.quote?.change_pct) }}
              </TableCell>
              <TableCell class="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                {{ currentOpportunity(row) ? fmt(currentOpportunity(row)?.quality_score, 0) + '分 · ' + opportunityKinds[currentOpportunity(row)!.kind] : '—' }}
              </TableCell>
              <TableCell class="font-semibold tabular-nums">
                {{ fmt(row.analysis?.score, 0) }}
                <small v-if="row.analysis && (row.analysis.reference || now.getTime() - row.analysis.as_of >= 90_000 || !status.endsWith('已连接'))">参考分</small>
              </TableCell>
              <TrendDirectionCell :direction="currentOpportunity(row)?.direction ?? row.analysis?.direction" />
              <TableCell>{{ row.analysis?.state ? stages[row.analysis.state] : '—' }}</TableCell>
              <TrendWindowCell
                v-for="n in [5, 15, 30, 60]"
                :key="n"
                :window="row.analysis?.windows?.[n]"
              />
              <TableCell class="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                {{ format(row.quote?.turnover, 0) }}
              </TableCell>
              <TableCell class="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                {{ percent(row.quote?.funding_rate == null ? null : row.quote.funding_rate * 100, 4) }}
              </TableCell>
              <TableCell
                v-if="admin"
                class="sticky right-0 z-10 bg-background px-4 py-2 text-right"
                @click.stop
              >
                <Button
                  variant="ghost"
                  size="sm"
                  class="text-destructive"
                  :aria-label="'移除 ' + row.symbol"
                  :disabled="busy"
                  @click="removing = row.symbol"
                >
                  <Trash2 class="size-4" /> 删除
                </Button>
              </TableCell>
            </TableRow>
            <TableRow
              v-if="symbol === row.symbol"
              data-testid="contract-expanded-row"
            >
              <TableCell
                :colspan="columns.length + (admin ? 1 : 0)"
                class="max-w-0 p-3"
              >
                <ContractMarketPanel
                  v-model:interval="interval"
                  :row="row"
                  :bars="chartBars"
                  :current="chartCurrent"
                  :loading="loadingDaily || !chartReceived"
                  :error="chartError"
                  @retry="loadDaily"
                />
              </TableCell>
            </TableRow>
          </template>
        </TableBody>
      </Table>
      <p
        v-if="!rows.length"
        class="p-8 text-center text-sm text-muted-foreground"
      >
        {{ received ? '暂无标的' : '正在连接行情…' }}
      </p>
    </section>

    <ContractAddDialog
      v-if="admin"
      v-model:open="addOpen"
      :existing="existingSymbols"
      :busy="busy"
      :add-error="addError"
      @add="add"
    />
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
