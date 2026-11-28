<script setup lang="ts">
import InstrumentTable from '@/components/market-data/instrument-table/InstrumentTable.vue';
import InstrumentRow from '@/components/market-data/instrument-table/InstrumentRow.vue';
import TrendWindowCell from '@/components/market-data/TrendWindowCell.vue';
import TrendDirectionCell from '@/components/market-data/TrendDirectionCell.vue';
import { opportunityKinds, stages, fmt } from '@/components/intraday-options/labels';
import { computed, onBeforeUnmount, ref } from 'vue';
import { Heart, MoreHorizontal, Plus, Trash2 } from 'lucide-vue-next';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { TableHeader, TableBody, TableRow, TableCell, TableHead } from '@/components/ui/table';
import { contractsApi, type Contract, type ContractQuote, type MarketSnapshot } from '@/api/contracts';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import TrendStatus from '@/components/stocks/TrendStatus.vue';
import PatternStatus from '@/components/stocks/PatternStatus.vue';
import { trendSortValue, patternSortValue } from '@/utils/realtimeTableSort';
import { toCamelCase } from '@/api/utils';
import type { RealtimeTrend, RealtimePatternState } from '@/api/realtimeMarket';
import ContractRowChart from '@/components/contracts/ContractRowChart.vue';
import ContractDetailDialog from '@/components/contracts/ContractDetailDialog.vue';
import ContractLink from '@/components/contracts/ContractLink.vue';
import ContractAddDialog from '@/components/contracts/ContractAddDialog.vue';
import { signedTextClass } from '@/utils/marketTone';
import { useTableSort, sortField } from '@/composables/useTableSort';
import { useContractMarket } from '@/composables/useContractMarket';
import { useAuthStore } from '@/stores/authStore';
import { useCurrentTime } from '@/composables/useCurrentTime';

const selectedSymbol = ref('');
const selectedContract = computed(() => displayRows.value.find(row => row.symbol === selectedSymbol.value));
const rows = ref<ContractQuote[]>([]);
const favorites = ref<string[]>([]);
const savingFavorite = ref(true);
void contractsApi.favorites().then(value => { if (Array.isArray(value)) favorites.value = value; })
  .catch(err => { error.value = getParsedApiError(err); }).finally(() => { savingFavorite.value = false; });
async function toggleFavorite(symbol: string) {
  if (savingFavorite.value) return;
  savingFavorite.value = true;
  try { favorites.value = await contractsApi.favorite(symbol, !favorites.value.includes(symbol)); }
  catch (err) { error.value = getParsedApiError(err); }
  finally { savingFavorite.value = false; }
}
const received = ref(false);
const error = ref<ParsedApiError | null>(null);
const addOpen = ref(false);
const addError = ref<ParsedApiError | null>(null);
const busy = ref(false);
const removing = ref('');
const auth = useAuthStore();
const admin = computed(() => auth.currentUser?.role === 'admin');
const now = useCurrentTime(5_000);
function opportunityStatus(row: ContractQuote) {
  if (!row.analysis) return '等待分钟线';
  if (!status.value.endsWith('已连接') || delayed(row) || now.value.getTime() - row.analysis.as_of >= 90_000) return '行情延迟';
  return row.analysis.windows[15]?.dataStatus !== 'ready' ? '数据不足' : '暂无确认';
}
function currentOpportunity(row: ContractQuote) {
  const analysis = row.analysis;
  return analysis && !delayed(row) && status.value.endsWith('已连接') && now.value.getTime() - analysis.as_of < 90_000
    && (!analysis.opportunity?.expires_at || now.value.getTime() < Date.parse(analysis.opportunity.expires_at))
    ? analysis.opportunity : null;
}
const metricPeriod = 5 * 60_000;
const metricGrace = 60_000;
const maxMetricDelay = 15 * 60_000;
const displayRows = computed(() => {
  const stamp = now.value.getTime();
  const boundary = Math.floor(stamp / metricPeriod) * metricPeriod;
  return rows.value.map(row => ({
    ...row,
    list_metrics: Object.fromEntries(Object.entries(row.list_metrics ?? {}).filter(([, reading]) =>
      reading.timestamp <= stamp && stamp - reading.timestamp <= metricPeriod + maxMetricDelay)),
    trend: toCamelCase<RealtimeTrend | null>(row.analysis?.trend_1m ?? null),
    pattern: toCamelCase<RealtimePatternState | null>(row.analysis?.pattern_1m ?? null),
    mark: row.mark && Math.abs(stamp - row.mark.timestamp) < 60000 ? row.mark : null,
    book: row.book && Math.abs(stamp - row.book.timestamp) < 60000 ? row.book : null,
    metrics: row.metrics?.timestamp === boundary ? row.metrics : null,
  }));
});
const sort = useTableSort(() => displayRows.value, (row, key) => {
  if (key === 'trend') return trendSortValue(row.trend);
  if (key === 'pattern') return patternSortValue(row.pattern);
  if (key === 'opportunity') return currentOpportunity(row)?.quality_score;
  if (key === 'direction') return currentOpportunity(row)?.direction ?? row.analysis?.direction;
  return sortField(row, key);
});
sort.sortKey = 'quote.turnover';
sort.direction = 'desc';
const orderedRows = computed(() => {
  const pinned = new Set(favorites.value);
  return [...sort.sorted.filter(row => pinned.has(row.symbol)), ...sort.sorted.filter(row => !pinned.has(row.symbol))];
});
const existingSymbols = computed(() => rows.value.map(row => row.symbol));
const priceChangeColumn = { key: 'list_metrics.price_change.value', label: '1h 涨跌幅', unit: 'change', description: '同一 UTC 窗口内，末分钟收盘价相对首分钟开盘价的变化。' };
const flowColumns = [
  { key: 'list_metrics.oi_change.value', label: '1h OI 数量变化', unit: 'change', description: '期末与一小时前的未平仓合约数量变化率。' },
  { key: 'list_metrics.buy_share.value', label: '1h 主动买入占比', unit: 'share', description: '整小时主动买入量占主动买卖成交量之和的比例，按成交量加权。' },
  { key: 'list_metrics.account_ratio.value', label: '账户多空比', unit: 'multiple', description: '全市场净多账户数 / 净空账户数。大户持仓多空比按仓位规模计算。' },
];
const metricColumns = [priceChangeColumn, ...flowColumns];
function metricDelayed(row: ContractQuote, key: string) {
  const reading = row.list_metrics?.[key.split('.')[1]!];
  return reading && now.value.getTime() - reading.timestamp > metricPeriod + metricGrace;
}
function metricText(row: ContractQuote, column: typeof metricColumns[number]) {
  const value = sortField(row, column.key);
  if (typeof value !== 'number') return '—';
  if (column.unit === 'multiple') return value.toFixed(2);
  if (column.unit === 'share') return (value * 100).toFixed(2) + '%';
  const coverage = row.list_metrics?.[column.key.split('.')[1]!]?.available_minutes;
  return percent(value * 100) + (coverage ? ` · ${coverage}/60 分钟参考` : '');
}
const columns = [
  { key: 'symbol', label: '合约' },
  { key: 'quote.price', label: '最新价' }, { key: 'quote.change_pct', label: '24h 涨跌幅' },
  { key: 'trend', label: '趋势持续' }, { key: 'pattern', label: '最近形态' }, priceChangeColumn,
  { key: 'opportunity', label: '短线机会' }, { key: 'analysis.score', label: '趋势质量分' },
  { key: 'direction', label: '当前方向' }, { key: 'analysis.state', label: '当前状态' },
  ...[5, 15, 30, 60].map(n => ({ key: `analysis.windows.${n}.score`, label: `${n}分钟` })),
  ...flowColumns,
];
let stopped = false;
function receive(snapshot: MarketSnapshot) {
  if (!received.value) error.value = null;
  received.value = true;
  rows.value = snapshot.items;
}
const { status, reconnect } = useContractMarket(ref(''), ref('1m'), receive);
void contractsApi.snapshot().then(snapshot => {
  if (!stopped && !received.value) receive(snapshot);
}).catch(err => {
  if (!stopped && !received.value) error.value = getParsedApiError(err);
});
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
      reconnect();
    }
  } catch (err) { if (!stopped) error.value = getParsedApiError(err); }
  finally { busy.value = false; }
}
function formatPrice(value: number | null | undefined) {
  return value == null ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: 10 });
}
function percent(value: number | null | undefined) {
  return value == null ? '—' : (value > 0 ? '+' : '') + value.toFixed(2) + '%';
}
function categoryLabel(category: string) {
  return ({ COIN: '加密货币', EQUITY: '股票/ETF', KR_EQUITY: '韩股', COMMODITY: '商品' } as Record<string, string>)[category] ?? category;
}
function delayed(row: ContractQuote) {
  return !row.quote || Math.abs(now.value.getTime() - row.quote.timestamp) > 60_000;
}
onBeforeUnmount(() => { stopped = true; });
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
            点击行展开行情，点击名称查看标的详情 · 日内分析从 UTC 00:00 起使用已收盘分钟线
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
      <InstrumentTable freeze-favorite>
        <TableHeader>
          <TableRow>
            <SortableTableHeader
              label="关注"
              class="instrument-column px-2"
              description="已关注合约置顶。点击切换各组内的 24 小时成交额排序。"
              v-bind="sort.header('quote.turnover')"
            />
            <SortableTableHeader
              v-for="column in columns"
              :key="column.key"
              :label="column.label"
              :description="metricColumns.find(c => c.key === column.key)?.description"
              :align="column.key.startsWith('quote.') ? 'right' : 'left'"
              v-bind="sort.header(column.key)"
              :class="{ 'instrument-column': column.key === 'symbol' }"
            />
            <TableHead
              v-if="admin"
              class="px-4 text-right"
            >
              操作
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <template
            v-for="row in orderedRows"
            :key="row.symbol"
          >
            <InstrumentRow
              :symbol="row.symbol"
              all-periods
              data-testid="contract-row"
              class="cursor-pointer"
            >
              <TableCell class="instrument-column px-2">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  :disabled="savingFavorite"
                  :aria-pressed="favorites.includes(row.symbol)"
                  :aria-label="`关注 ${row.symbol}`"
                  @click.stop="toggleFavorite(row.symbol)"
                >
                  <Heart :class="favorites.includes(row.symbol) ? 'fill-current text-brand' : 'text-muted-foreground'" />
                </Button>
              </TableCell>
              <TableCell
                class="instrument-column px-4 py-3"
              >
                <ContractLink
                  :symbol="row.symbol"
                  :contract="row"
                  @open-contract="selectedSymbol = row.symbol"
                />
                <span class="ml-1 text-xs text-muted-foreground">· {{ categoryLabel(row.category) }}</span>
                <span
                  v-if="delayed(row)"
                  class="ml-2 text-xs text-muted-foreground"
                >{{ row.quote ? '延迟' : '暂无行情' }}</span>
              </TableCell>
              <TableCell class="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                {{ formatPrice(row.quote?.price) }}
              </TableCell>
              <TableCell
                class="whitespace-nowrap px-4 py-3 text-right tabular-nums"
                :class="signedTextClass(row.quote?.change_pct)"
              >
                {{ percent(row.quote?.change_pct) }}
              </TableCell>
              <TableCell><TrendStatus :trend="row.trend" /></TableCell>
              <TableCell>
                <PatternStatus
                  :pattern="row.pattern"
                  :now="now"
                />
              </TableCell>
              <TableCell class="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                {{ metricText(row, priceChangeColumn) }}
                <small
                  v-if="metricDelayed(row, priceChangeColumn.key)"
                  class="text-muted-foreground"
                >数据延迟</small>
              </TableCell>
              <TableCell class="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                {{ currentOpportunity(row) ? fmt(currentOpportunity(row)?.quality_score, 0) + '分 · ' + opportunityKinds[currentOpportunity(row)!.kind] : opportunityStatus(row) }}
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
              <TableCell
                v-for="column in flowColumns"
                :key="column.key"
                class="whitespace-nowrap px-4 py-3 text-right tabular-nums"
              >
                {{ metricText(row, column) }}
                <small
                  v-if="metricDelayed(row, column.key)"
                  class="text-muted-foreground"
                >数据延迟</small>
              </TableCell>
              <TableCell
                v-if="admin"
                class="px-4 py-2 text-right"
                @click.stop
              >
                <DropdownMenu>
                  <DropdownMenuTrigger as-child>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      :aria-label="row.symbol + ' 合约操作'"
                      :disabled="busy"
                    >
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      variant="destructive"
                      @select="removing = row.symbol"
                    >
                      <Trash2 />删除
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </TableCell>
              <template #chart="{ period }">
                <ContractRowChart
                  :row="row"
                  :period="period"
                />
              </template>
            </InstrumentRow>
          </template>
        </TableBody>
      </InstrumentTable>
      <p
        v-if="!rows.length"
        class="p-8 text-center text-sm text-muted-foreground"
      >
        {{ received ? '暂无标的' : '正在连接行情…' }}
      </p>
    </section>

    <ContractDetailDialog
      v-if="selectedContract"
      :key="selectedContract.symbol"
      :row="selectedContract"
      @close="selectedSymbol = ''"
    />
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
