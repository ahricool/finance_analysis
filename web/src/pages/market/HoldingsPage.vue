<script setup lang="ts">
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import {
  holdingsApi,
  tradeEngineApi,
  type PortfolioAccount,
  type PortfolioPosition,
  type TradeEnginePosition,
  type HoldingsSummary,
} from '@/api/holdings';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import RealtimeStatus from '@/components/stocks/RealtimeStatus.vue';
import IntradayStockPanel from '@/components/stocks/IntradayStockPanel.vue';
import TrendStatus from '@/components/stocks/TrendStatus.vue';
import PatternStatus from '@/components/stocks/PatternStatus.vue';
import IntradayDirectionStatus from '@/components/stocks/IntradayDirectionStatus.vue';
import { useCurrentTime } from '@/composables/useCurrentTime';
import { useRealtimeQuotes } from '@/composables/useRealtimeQuotes';
import { signedTextClass } from '@/utils/marketTone';
import StockAutocomplete from '@/components/StockAutocomplete/StockAutocomplete.vue';
import type { AssetType, Market } from '@/types/stockIndex';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { MoreHorizontal } from 'lucide-vue-next';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { createOperationId } from '@/utils/operationId';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

const market = ref<'CN' | 'US'>('CN');
const { portfolio: livePortfolio, status: realtimeStatus, getQuote } = useRealtimeQuotes(() => ({ scope: 'holdings', market: market.value }));
const currentTime = useCurrentTime();
const expandedId = ref<number | null>(null);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const accounts = ref<PortfolioAccount[]>([]);
const positions = ref<PortfolioPosition[]>([]);
const cash = ref('0');
const marketValue = ref('0');
const totalAsset = ref('0');
const exposure = ref<string | null>(null);
const missingQuotes = ref(0);
const updatedAt = ref<string | null>(null);
type SortKey = 'symbol' | 'currentPrice' | 'changePct' | 'engine' | 'quantity' | 'averageCost' | 'weight' | 'dayPnl' | 'unrealizedPnlPct';
const sortKey = ref<SortKey>('weight');
const sortDirection = ref<'asc' | 'desc'>('desc');
const columns: Array<{ key: SortKey; label: string }> = [
  { key: 'symbol', label: '股票' }, { key: 'currentPrice', label: '现价' },
  { key: 'changePct', label: '当日涨跌' }, { key: 'engine', label: '交易引擎' },
  { key: 'quantity', label: '数量' }, { key: 'averageCost', label: '成本' },
  { key: 'weight', label: '仓位' }, { key: 'dayPnl', label: '当日盈亏' }, { key: 'unrealizedPnlPct', label: '盈亏' },
];
const engine = ref<TradeEnginePosition[]>([]);
const formOpen = ref(false);
const formKind = ref<'buy' | 'sell' | 'cash'>('buy');
const formSymbol = ref('');
const selectedSymbol = ref('');
const selectedAssetType = ref('STOCK');
const selectionError = ref('');
const formQuantity = ref('');
const formPrice = ref('');
const formAmount = ref('');
const formPositionId = ref<number | null>(null);
const saving = ref(false);
const detail = ref<PortfolioPosition | null>(null);
const engineLoading = ref(false);
const engineError = ref<ParsedApiError | null>(null);
const formError = ref<ParsedApiError | null>(null);
const operationId = ref('');
let listRequest = 0;
let engineRequest = 0;
let formRequest = 0;
let stopped = false;
onBeforeUnmount(() => {
  stopped = true;
  listRequest++; engineRequest++; formRequest++;
});
const account = computed(() => accounts.value[0] || null);

onMounted(() => {
  void load();
});
const engineByPosition = computed(() => Object.fromEntries(engine.value.map(item => [item.positionId, item])));
function numeric(value?: string | null): number | null {
  return value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
}
function engineLabel(row: PortfolioPosition) {
  if (row.tradeEngineEnabled === false) return '已关闭';
  if (engineLoading.value) return '加载中';
  if (engineError.value) return '读取失败';
  return engineByPosition.value[String(row.id)]?.action || '暂无正式信号';
}
const sortedPositions = computed(() => [...positions.value].sort((a, b) => {
  const key = sortKey.value;
  const left = key === 'symbol' ? a.name || a.symbol : key === 'engine' ? engineLabel(a) : numeric(a[key]);
  const right = key === 'symbol' ? b.name || b.symbol : key === 'engine' ? engineLabel(b) : numeric(b[key]);
  if (left == null) return right == null ? a.id - b.id : 1;
  if (right == null) return -1;
  const order = typeof left === 'number' && typeof right === 'number' ? left - right : String(left).localeCompare(String(right), 'zh-CN');
  return order ? order * (sortDirection.value === 'asc' ? 1 : -1) : a.id - b.id;
}));
function sort(key: SortKey) {
  if (sortKey.value === key) sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc';
  else { sortKey.value = key; sortDirection.value = key === 'symbol' || key === 'engine' ? 'asc' : 'desc'; }
}
function signed(value?: string | null, suffix = '') {
  const number = numeric(value);
  return number == null ? '—' : `${number > 0 ? '+' : ''}${number.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${suffix}`;
}
function quoteTime(value?: string | null, compact = false) {
  if (!value) return '时间未知';
  const options: Intl.DateTimeFormatOptions = { timeZone: market.value === 'CN' ? 'Asia/Shanghai' : 'America/New_York', hour12: false };
  if (compact) Object.assign(options, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  return new Date(value).toLocaleString('zh-CN', options);
}
function quoteSource(row: PortfolioPosition) {
  return ({ fuyao: '扶摇', longbridge: 'Longbridge', streaming: '行情流', yfinance: 'Yahoo' } as Record<string, string>)[row.quoteSource || ''] || '来源未知';
}
function applySummary(summary: HoldingsSummary) {
  if (summary.market !== market.value) return;
  if (summary.generatedAt && updatedAt.value && Date.parse(summary.generatedAt) < Date.parse(updatedAt.value)) return;
  accounts.value = summary.accounts; positions.value = summary.positions;
  cash.value = summary.cash; marketValue.value = summary.marketValue;
  totalAsset.value = summary.totalAsset; exposure.value = summary.grossExposure;
  missingQuotes.value = summary.missingQuoteCount ?? summary.positions.filter(row => row.currentPrice == null).length;
  updatedAt.value = summary.generatedAt || null;
  error.value = null;
}
watch(livePortfolio, summary => { if (summary) applySummary(summary); });

function fmt(value?: string | null) {
  if (value == null || value === '') return '-';
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString(undefined, { maximumFractionDigits: 4 }) : value;
}

async function loadSummary() {
  const request = ++listRequest;
  const requestedMarket = market.value;
  loading.value = true;
  error.value = null;
  try {
    const summary = await holdingsApi.summary(requestedMarket);
    if (stopped || request !== listRequest || requestedMarket !== market.value) return;
    applySummary(summary);
  } catch (err) {
    if (!stopped && request === listRequest) error.value = getParsedApiError(err);
  } finally {
    if (!stopped && request === listRequest) loading.value = false;
  }
}

async function loadEngine() {
  const request = ++engineRequest;
  const requestedMarket = market.value;
  engineLoading.value = true;
  engineError.value = null;
  engine.value = [];
  try {
    const views = await tradeEngineApi.positions(requestedMarket);
    if (!stopped && request === engineRequest && requestedMarket === market.value) engine.value = views;
  } catch (err) {
    if (!stopped && request === engineRequest) engineError.value = getParsedApiError(err);
  } finally {
    if (!stopped && request === engineRequest) engineLoading.value = false;
  }
}

async function load() {
  await Promise.all([loadSummary(), loadEngine()]);
}

function changeMarket(value: 'CN' | 'US') {
  if (value === market.value) return;
  market.value = value;
  expandedId.value = null;
  closeDetail();
  closeForm();
  accounts.value = [];
  positions.value = [];
  cash.value = marketValue.value = totalAsset.value = '';
  exposure.value = null;
  updatedAt.value = null;
  missingQuotes.value = 0;
  void load();
}

function closeForm() {
  formRequest++;
  formOpen.value = false;
  saving.value = false;
  formError.value = null;
}

function openForm(kind: typeof formKind.value, row?: PortfolioPosition) {
  if (!account.value || loading.value || error.value) return;
  formRequest++;
  operationId.value = createOperationId();
  formError.value = null;
  saving.value = false;
  formKind.value = kind;
  formSymbol.value = row?.symbol || '';
  selectedSymbol.value = row?.symbol || '';
  selectedAssetType.value = row?.assetType || 'STOCK';
  selectionError.value = '';
  formQuantity.value = '';
  formPrice.value = row?.currentPrice || '';
  formAmount.value = kind === 'cash' ? account.value?.cash || '0' : '';
  formPositionId.value = row?.id ?? null;
  formOpen.value = true;
}

function selectInstrument(code: string, _name?: string, source?: 'manual' | 'autocomplete', selectedMarket?: Market, assetType?: AssetType) {
  selectedSymbol.value = '';
  if (source !== 'autocomplete') {
    selectionError.value = '请从搜索建议中选择股票或 ETF';
    return;
  }
  if (selectedMarket !== market.value || !['stock', 'etf'].includes(assetType || '')) {
    selectionError.value = '请选择当前市场的股票或 ETF';
    return;
  }
  selectedSymbol.value = code;
  selectedAssetType.value = assetType!.toUpperCase();
  selectionError.value = '';
}

async function submitForm() {
  if (!account.value || saving.value || loading.value || error.value || !formOpen.value) return;
  if (formKind.value === 'buy' && !selectedSymbol.value) return;
  const request = formRequest;
  const submittedMarket = market.value;
  saving.value = true;
  formError.value = null;
  try {
    if (formKind.value === 'cash') await holdingsApi.setCash({ operationId: operationId.value, accountId: account.value.id, amount: formAmount.value });
    else if (formKind.value === 'buy') {
      await holdingsApi.buy({ operationId: operationId.value, accountId: account.value.id, symbol: selectedSymbol.value, assetType: selectedAssetType.value, quantity: formQuantity.value, price: formPrice.value });
    } else if (formPositionId.value != null) {
      await holdingsApi.sell({ operationId: operationId.value, positionId: formPositionId.value, quantity: formQuantity.value, price: formPrice.value });
    }
    if (stopped || request !== formRequest || submittedMarket !== market.value) return;
    formOpen.value = false;
    closeDetail();
    await load();
  } catch (err) {
    if (!stopped && request === formRequest) formError.value = getParsedApiError(err);
  } finally {
    if (!stopped && request === formRequest) saving.value = false;
  }
}

function openDetail(row: PortfolioPosition) {
  detail.value = row;
}
function closeDetail() {
  detail.value = null;
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      variant="section"
      title="投资组合"
      en="Portfolio"
      description="管理实际持仓与账户现金，查看资产分布、持仓盈亏和调仓建议。"
    >
      <template #title-actions>
        <div
          role="group"
          aria-label="投资组合市场"
          class="inline-flex items-center gap-1 rounded-lg bg-muted/80 p-1 ring-1 ring-border/50"
        >
          <Button
            variant="ghost"
            size="sm"
            :class="market === 'CN' ? 'bg-background text-foreground shadow-sm hover:bg-background' : 'text-muted-foreground'"
            :aria-pressed="market === 'CN'"
            data-testid="market-cn"
            @click="changeMarket('CN')"
          >
            A 股
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :class="market === 'US' ? 'bg-background text-foreground shadow-sm hover:bg-background' : 'text-muted-foreground'"
            :aria-pressed="market === 'US'"
            data-testid="market-us"
            @click="changeMarket('US')"
          >
            美股
          </Button>
        </div>
      </template>
    </PageHeader>

    <ApiErrorAlert
      v-if="error"
      :error="error"
    />

    <Button
      v-if="error"
      variant="outline"
      @click="loadSummary"
    >
      重试持仓
    </Button>
    <div
      v-if="engineError"
      data-testid="engine-error"
      class="space-y-2"
    >
      <p class="text-sm font-medium">
        Trade Engine 建议读取失败
      </p>
      <ApiErrorAlert :error="engineError" />
      <Button
        data-testid="retry-engine"
        variant="outline"
        @click="loadEngine"
      >
        重试建议
      </Button>
    </div>

    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Card>
        <CardHeader>
          <CardDescription>
            <IndicatorHelpLabel
              scope="holdings"
              label="总资产"
              compact
            />
          </CardDescription><CardTitle data-testid="total-asset">
            {{ fmt(totalAsset) }}
          </CardTitle>
        </CardHeader>
      </Card>
      <Card>
        <CardHeader>
          <CardDescription>
            <IndicatorHelpLabel
              scope="holdings"
              label="现金"
              compact
            />
          </CardDescription><CardTitle data-testid="cash">
            {{ fmt(cash) }}
          </CardTitle>
        </CardHeader>
      </Card>
      <Card>
        <CardHeader>
          <CardDescription>
            <IndicatorHelpLabel
              scope="holdings"
              label="持仓市值"
              compact
            />
          </CardDescription><CardTitle>{{ fmt(marketValue) }}</CardTitle>
        </CardHeader>
      </Card>
      <Card>
        <CardHeader>
          <CardDescription>
            <IndicatorHelpLabel
              scope="holdings"
              label="总仓位"
              compact
            />
          </CardDescription><CardTitle>{{ exposure ? `${(Number(exposure) * 100).toFixed(1)}%` : '-' }}</CardTitle>
        </CardHeader>
      </Card>
    </div>

    <div class="flex flex-wrap gap-2">
      <Button
        variant="outline"
        :disabled="loading"
        @click="load"
      >
        刷新
      </Button>
      <Button
        data-testid="action-cash"
        :disabled="!account || loading || !!error"
        @click="openForm('cash')"
      >
        修改现金
      </Button>
      <Button
        variant="outline"
        data-testid="action-buy"
        :disabled="!account || loading || !!error"
        @click="openForm('buy')"
      >
        买入
      </Button>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <RealtimeStatus :status="realtimeStatus" />
      <span class="self-center text-xs text-muted-foreground">
        {{ market === 'CN' ? '人民币 CNY · 上海时间' : '美元 USD · 纽约时间' }}
        <template v-if="updatedAt"> · 更新于 {{ quoteTime(updatedAt) }}</template>
      </span>
    </div>

    <p
      v-if="missingQuotes"
      role="status"
      class="text-sm text-warning"
      data-testid="valuation-incomplete"
    >
      估值不完整：{{ missingQuotes }} 只持仓暂无有效报价，总资产与仓位仅包含已获报价的持仓。
    </p>
    <Card>
      <CardHeader>
        <CardTitle>持仓</CardTitle>
        <CardDescription>{{ account?.name || '默认账户' }}</CardDescription>
      </CardHeader>
      <CardContent>
        <Empty v-if="!loading && !error && !positions.length">
          <EmptyHeader>
            <EmptyTitle>暂无持仓</EmptyTitle>
            <EmptyDescription>记录买入以添加持仓，现金可独立修改。</EmptyDescription>
          </EmptyHeader>
        </Empty>
        <Table v-else>
          <TableHeader>
            <TableRow>
              <SortableTableHeader
                v-for="column in columns"
                :key="column.key"
                :class="column.key === 'symbol' ? 'sticky left-0 z-10 bg-muted px-2' : 'px-2'"
                :label="column.label"
                scope="holdings"
                :active="sortKey === column.key"
                :direction="sortDirection"
                :align="column.key === 'symbol' || column.key === 'engine' ? 'left' : 'right'"
                @sort="sort(column.key)"
              />
              <TableHead>趋势持续</TableHead><TableHead>最近形态</TableHead><TableHead>日内方向状态</TableHead>
              <TableHead>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <template
              v-for="row in sortedPositions"
              :key="row.id"
            >
              <TableRow
                data-testid="position-row"
                class="cursor-pointer"
                tabindex="0"
                :aria-label="`展开 ${row.name || row.symbol} 分钟行情`"
                :aria-expanded="expandedId === row.id"
                @click="expandedId = expandedId === row.id ? null : row.id"
                @keydown.enter.self="expandedId = expandedId === row.id ? null : row.id"
                @keydown.space.self.prevent="expandedId = expandedId === row.id ? null : row.id"
              >
                <TableCell class="sticky left-0 z-10 bg-background">
                  <button
                    class="text-left font-medium"
                    @click.stop="openDetail(row)"
                  >
                    <span class="block">{{ row.name || row.symbol }}</span>
                    <span
                      v-if="row.name"
                      class="block text-xs font-normal text-muted-foreground"
                    >{{ row.symbol }}</span>
                  </button>
                </TableCell>
                <TableCell class="text-right tabular-nums">
                  <span class="font-medium">{{ fmt(row.currentPrice) }}</span>
                  <span
                    v-if="row.quoteStatus === 'delayed'"
                    class="ml-1 text-xs text-warning"
                  >延迟</span>
                  <span
                    v-if="row.currentPrice == null"
                    class="block text-xs text-muted-foreground"
                  >暂无报价</span>
                  <TooltipProvider v-else>
                    <Tooltip>
                      <TooltipTrigger as-child>
                        <span
                          tabindex="0"
                          class="block whitespace-nowrap text-xs text-muted-foreground"
                        >{{ quoteSource(row) }} · {{ quoteTime(row.quoteTime, true) }}</span>
                      </TooltipTrigger>
                      <TooltipContent>报价时间：{{ quoteTime(row.quoteTime) }} · {{ quoteSource(row) }}</TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </TableCell>
                <TableCell
                  class="text-right tabular-nums"
                  :class="signedTextClass(numeric(row.changePct))"
                >
                  <span class="block font-medium">{{ signed(row.changePct, '%') }}</span>
                  <span class="block text-xs">{{ signed(row.changeAmount) }}</span>
                </TableCell>
                <TableCell class="whitespace-nowrap">
                  {{ engineLabel(row) }}
                </TableCell>
                <TableCell class="text-right tabular-nums">
                  {{ fmt(row.quantity) }}
                </TableCell>
                <TableCell class="text-right tabular-nums">
                  {{ fmt(row.averageCost) }}
                </TableCell>
                <TableCell class="text-right tabular-nums">
                  {{ row.weight != null ? `${(Number(row.weight) * 100).toFixed(1)}%` : '—' }}
                </TableCell>
                <TableCell
                  class="text-right tabular-nums"
                  :class="signedTextClass(numeric(row.dayPnl))"
                >
                  {{ signed(row.dayPnl) }}
                </TableCell>
                <TableCell
                  class="text-right tabular-nums"
                  :class="signedTextClass(numeric(row.unrealizedPnl))"
                >
                  <span class="block font-medium">{{ signed(row.unrealizedPnlPct, '%') }}</span>
                  <span class="block text-xs">{{ signed(row.unrealizedPnl) }}</span>
                </TableCell>
                <TableCell><TrendStatus :trend="getQuote(row.symbol, market)?.trend_1m" /></TableCell>
                <TableCell><PatternStatus :pattern="getQuote(row.symbol, market)?.pattern_1m" /></TableCell>
                <TableCell>
                  <IntradayDirectionStatus
                    :quote="getQuote(row.symbol, market)"
                    :market-type="market"
                    :now="currentTime"
                  />
                </TableCell>
                <TableCell @click.stop>
                  <DropdownMenu>
                    <DropdownMenuTrigger as-child>
                      <Button
                        size="icon"
                        variant="ghost"
                        :disabled="loading || !!error"
                        :aria-label="`${row.name || row.symbol}持仓操作`"
                      >
                        <MoreHorizontal class="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem @select="openForm('buy', row)">
                        买入
                      </DropdownMenuItem>
                      <DropdownMenuItem @select="openForm('sell', row)">
                        卖出
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
              <TableRow v-if="expandedId === row.id">
                <TableCell
                  :colspan="columns.length + 4"
                  class="max-w-0 p-3"
                >
                  <IntradayStockPanel
                    :symbol="row.symbol"
                    :market="market"
                  />
                </TableCell>
              </TableRow>
            </template>
          </TableBody>
        </Table>
      </CardContent>
    </Card>

    <Dialog
      :open="formOpen"
      @update:open="value => { if (!value) closeForm(); }"
    >
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>{{ { buy: '买入', sell: '卖出', cash: '修改现金' }[formKind] }}</DialogTitle>
          <DialogDescription>{{ formKind === 'cash' ? '设置当前现金，用于仓位与风险计算；买卖不会自动改变现金。' : '记录实际持仓变动，不改变现金。' }}</DialogDescription>
        </DialogHeader>
        <ApiErrorAlert
          v-if="formError"
          :error="formError"
        />
        <fieldset
          :disabled="saving"
          class="space-y-3"
        >
          <template v-if="formKind === 'buy' || formKind === 'sell'">
            <div v-if="formKind === 'buy'">
              <Label>股票</Label>
              <StockAutocomplete
                :model-value="formSymbol"
                :teleported="false"
                data-testid="form-symbol"
                @update:model-value="value => { formSymbol = value; selectedSymbol = ''; selectionError = ''; }"
                @submit="selectInstrument"
              />
              <p
                v-if="selectionError"
                class="mt-1 text-sm text-destructive"
              >
                {{ selectionError }}
              </p>
              <p
                v-else
                class="mt-1 text-sm text-muted-foreground"
              >
                {{ selectedSymbol || '输入代码或名称，从建议中选择当前市场的股票或 ETF' }}
              </p>
            </div>
            <div>
              <Label>数量（股）</Label>
              <Input
                v-model="formQuantity"
                data-testid="form-quantity"
              />
            </div>
            <div>
              <Label>价格</Label>
              <Input
                v-model="formPrice"
                data-testid="form-price"
              />
            </div>
          </template>
          <div v-else>
            <Label>现金余额（{{ account?.currency }}）</Label>
            <Input
              v-model="formAmount"
              data-testid="form-amount"
            />
          </div>
        </fieldset>
        <DialogFooter>
          <Button
            variant="ghost"
            @click="closeForm"
          >
            取消
          </Button>
          <Button
            data-testid="form-submit"
            :disabled="saving || loading || !account || !!error || (formKind === 'buy' && !selectedSymbol)"
            @click="submitForm"
          >
            确认
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <StockDetailDialog
      :stock="detail ? { code: detail.symbol, name: null, market_type: market } : null"
      kind="research"
      initial-tab="holdings"
      :context="detail ? { accountId: detail.accountId, positionId: detail.id } : undefined"
      @update:open="value => { if (!value) closeDetail(); }"
      @holdings-updated="load"
    />
  </div>
</template>
