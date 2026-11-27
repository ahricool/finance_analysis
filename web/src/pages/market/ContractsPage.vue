<script setup lang="ts">
import InstrumentTable from '@/components/market-data/instrument-table/InstrumentTable.vue';
import InstrumentRow from '@/components/market-data/instrument-table/InstrumentRow.vue';
import TrendWindowCell from '@/components/market-data/TrendWindowCell.vue';
import TrendDirectionCell from '@/components/market-data/TrendDirectionCell.vue';
import { opportunityKinds, stages, fmt } from '@/components/intraday-options/labels';
import { computed, onBeforeUnmount, ref } from 'vue';
import { Plus, Trash2 } from 'lucide-vue-next';
import { Button } from '@/components/ui/button';
import { TableHeader, TableBody, TableRow, TableCell, TableHead } from '@/components/ui/table';
import { contractsApi, type Contract, type ContractQuote, type MarketSnapshot } from '@/api/contracts';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import ContractRowChart from '@/components/contracts/ContractRowChart.vue';
import ContractLink from '@/components/contracts/ContractLink.vue';
import ContractAddDialog from '@/components/contracts/ContractAddDialog.vue';
import { signedTextClass } from '@/utils/marketTone';
import { useTableSort, sortField } from '@/composables/useTableSort';
import { useContractMarket } from '@/composables/useContractMarket';
import { useAuthStore } from '@/stores/authStore';
import { useCurrentTime } from '@/composables/useCurrentTime';

const rows = ref<ContractQuote[]>([]);
const received = ref(false);
const error = ref<ParsedApiError | null>(null);
const addOpen = ref(false);
const addError = ref<ParsedApiError | null>(null);
const busy = ref(false);
const removing = ref('');
const auth = useAuthStore();
const admin = computed(() => auth.currentUser?.role === 'admin');
const now = useCurrentTime(5_000);
function currentOpportunity(row: ContractQuote) {
  const analysis = row.analysis;
  return analysis && !delayed(row) && status.value.endsWith('已连接') && now.value.getTime() - analysis.as_of < 90_000
    ? analysis.opportunity : null;
}
const displayRows = computed(() => {
  const stamp = now.value.getTime();
  const boundary = Math.floor(stamp / 300000) * 300000;
  return rows.value.map(row => ({
    ...row,
    mark: row.mark && Math.abs(stamp - row.mark.timestamp) < 60000 ? row.mark : null,
    book: row.book && Math.abs(stamp - row.book.timestamp) < 60000 ? row.book : null,
    metrics: row.metrics?.timestamp === boundary ? row.metrics : null,
  }));
});
function funding(row: ContractQuote) {
  if (row.mark) return row.mark.funding_rate;
  if (row.quote?.funding_timestamp != null || delayed(row)) return null;
  return row.quote?.funding_rate;
}
const sort = useTableSort(() => displayRows.value, (row, key) => {
  if (key === 'opportunity') return currentOpportunity(row)?.quality_score;
  if (key === 'quote.funding_rate') return funding(row);
  if (key === 'direction') return currentOpportunity(row)?.direction ?? row.analysis?.direction;
  return sortField(row, key);
});
sort.sortKey = 'opportunity';
sort.direction = 'desc';
const existingSymbols = computed(() => rows.value.map(row => row.symbol));
const metricColumns = [
  { key: 'metrics.price_change', label: '1h 涨跌幅', unit: 'change', description: '同一 UTC 窗口内，末分钟收盘价相对首分钟开盘价的变化。' },
  { key: 'metrics.oi_change', label: '1h OI 数量变化', unit: 'change', description: '期末与一小时前的未平仓合约数量变化率。' },
  { key: 'metrics.buy_share', label: '1h 主动买入占比', unit: 'share', description: '整小时主动买入量占主动买卖成交量之和的比例，按成交量加权。' },
  { key: 'metrics.accounts.ratio', label: '账户多空比', unit: 'multiple', description: '全市场净多账户数 / 净空账户数。大户持仓多空比按仓位规模计算。' },
];
function metricText(row: ContractQuote, column: typeof metricColumns[number]) {
  const value = sortField(row, column.key);
  if (typeof value !== 'number') return '—';
  if (column.unit === 'multiple') return value.toFixed(2);
  if (column.unit === 'share') return (value * 100).toFixed(2) + '%';
  return percent(value * 100);
}
const columns = [
  { key: 'symbol', label: '合约' }, { key: 'category', label: '分类' },
  { key: 'quote.price', label: '最新价' }, { key: 'quote.change_pct', label: '24h 涨跌幅' },
  ...metricColumns,
  { key: 'opportunity', label: '日内机会' }, { key: 'analysis.score', label: '趋势质量分' },
  { key: 'direction', label: '当前方向' }, { key: 'analysis.state', label: '当前状态' },
  ...[5, 15, 30, 60].map(n => ({ key: `analysis.windows.${n}.score`, label: `${n}分钟` })),
  { key: 'quote.turnover', label: '24h 成交额' }, { key: 'quote.funding_rate', label: '资金费率' },
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
      <InstrumentTable>
        <TableHeader>
          <TableRow>
            <SortableTableHeader
              v-for="column in columns"
              :key="column.key"
              :label="column.label"
              :description="metricColumns.find(c => c.key === column.key)?.description"
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
            <InstrumentRow
              :symbol="row.symbol"
              data-testid="contract-row"
              class="cursor-pointer"
            >
              <TableCell class="whitespace-nowrap px-4 py-3">
                <ContractLink
                  :symbol="row.symbol"
                  :contract="row"
                />
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
              <TableCell
                v-for="column in metricColumns"
                :key="column.key"
                class="whitespace-nowrap px-4 py-3 text-right tabular-nums"
              >
                {{ metricText(row, column) }}
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
                {{ percent(funding(row) == null ? null : funding(row)! * 100, 4) }}
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
