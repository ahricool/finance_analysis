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
} from '@/api/holdings';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import StockAutocomplete from '@/components/StockAutocomplete/StockAutocomplete.vue';
import type { AssetType, Market } from '@/types/stockIndex';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { createOperationId } from '@/utils/operationId';
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

const market = ref<'CN' | 'US'>('CN');
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const accounts = ref<PortfolioAccount[]>([]);
const positions = ref<PortfolioPosition[]>([]);
const cash = ref('0');
const marketValue = ref('0');
const totalAsset = ref('0');
const exposure = ref<string | null>(null);
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
    accounts.value = summary.accounts;
    positions.value = summary.positions;
    cash.value = summary.cash;
    marketValue.value = summary.marketValue;
    totalAsset.value = summary.totalAsset;
    exposure.value = summary.grossExposure;
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
  closeDetail();
  closeForm();
  accounts.value = [];
  positions.value = [];
  cash.value = marketValue.value = totalAsset.value = '';
  exposure.value = null;
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

    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
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
              <TableHead>
                <IndicatorHelpLabel
                  scope="holdings"
                  label="股票"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="holdings"
                  label="现价"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="holdings"
                  label="数量（股）"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="holdings"
                  label="平均成本"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="holdings"
                  label="市值"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="holdings"
                  label="仓位"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="holdings"
                  label="盈亏"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="holdings"
                  label="交易引擎"
                  compact
                />
              </TableHead>
              <TableHead>
                <IndicatorHelpLabel
                  scope="holdings"
                  label="操作"
                  compact
                />
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="row in positions"
              :key="row.id"
              data-testid="position-row"
            >
              <TableCell>
                <button
                  class="text-left font-medium"
                  @click="openDetail(row)"
                >
                  {{ row.symbol }}
                </button>
              </TableCell>
              <TableCell>{{ fmt(row.currentPrice) }}</TableCell>
              <TableCell>{{ fmt(row.quantity) }}</TableCell>
              <TableCell>{{ fmt(row.averageCost) }}</TableCell>
              <TableCell>{{ fmt(row.marketValue) }}</TableCell>
              <TableCell>{{ row.weight ? `${(Number(row.weight) * 100).toFixed(1)}%` : '-' }}</TableCell>
              <TableCell>{{ fmt(row.unrealizedPnl) }}</TableCell>
              <TableCell>{{ engineLoading ? '加载中' : engineError ? '读取失败' : engineByPosition[String(row.id)]?.action || '暂无正式信号' }}</TableCell>
              <TableCell class="space-x-2">
                <Button
                  size="sm"
                  variant="outline"
                  :disabled="loading || !!error"
                  @click="openForm('buy', row)"
                >
                  买入
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  :disabled="loading || !!error"
                  @click="openForm('sell', row)"
                >
                  卖出
                </Button>
              </TableCell>
            </TableRow>
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
