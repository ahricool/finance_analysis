<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import {
  holdingsApi,
  tradeEngineApi,
  type PortfolioAccount,
  type PortfolioPosition,
  type TradeEnginePosition,
} from '@/api/holdings';
import ResearchEvidence from '@/components/stocks/ResearchEvidence.vue';
import StockAutocomplete from '@/components/StockAutocomplete/StockAutocomplete.vue';
import type { AssetType, Market } from '@/types/stockIndex';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import DailyKLineCard from '@/components/market-data/DailyKLineCard.vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { createOperationId } from '@/utils/operationId';
import type { TradeMarker } from '@/lib/tradeMarkers';
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
const operations = ref<Array<{ executedAt: string; side: string; quantity: string; price: string }>>([]);
const markers = ref<TradeMarker[]>([]);
const engineLoading = ref(false);
const engineError = ref<ParsedApiError | null>(null);
const detailLoading = ref(false);
const detailError = ref<ParsedApiError | null>(null);
const toggleSaving = ref(false);
const formError = ref<ParsedApiError | null>(null);
const operationId = ref('');
let listRequest = 0;
let engineRequest = 0;
let detailRequest = 0;
let formRequest = 0;
let toggleRequest = 0;
let stopped = false;
onBeforeUnmount(() => {
  stopped = true;
  listRequest++; engineRequest++; detailRequest++; formRequest++; toggleRequest++;
});
const account = computed(() => accounts.value[0] || null);

onMounted(() => {
  void load();
});
const engineByPosition = computed(() => Object.fromEntries(engine.value.map(item => [item.positionId, item])));
const engineView = computed(() => detail.value ? engineByPosition.value[String(detail.value.id)] ?? null : null);

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

async function openDetail(row: PortfolioPosition) {
  const request = ++detailRequest;
  toggleRequest++;
  toggleSaving.value = false;
  detail.value = row;
  operations.value = [];
  markers.value = [];
  detailError.value = null;
  detailLoading.value = true;
  try {
    const [ops, marks] = await Promise.all([holdingsApi.operations(row.id), holdingsApi.markers(row.id)]);
    if (stopped || request !== detailRequest || detail.value?.id !== row.id) return;
    operations.value = ops;
    markers.value = marks.map(item => ({
      timestamp: Date.parse(item.timestamp), type: item.type, operations: item.operations,
    }));
  } catch (err) {
    if (!stopped && request === detailRequest) detailError.value = getParsedApiError(err);
  } finally {
    if (!stopped && request === detailRequest) detailLoading.value = false;
  }
}

async function toggleTradeEngine(enabled: boolean) {
  if (!detail.value || toggleSaving.value) return;
  const positionId = detail.value.id;
  const request = ++toggleRequest;
  toggleSaving.value = true;
  detailError.value = null;
  try {
    const updated = await holdingsApi.updatePosition(positionId, { tradeEngineEnabled: enabled });
    if (stopped || request !== toggleRequest || detail.value?.id !== positionId) return;
    detail.value = { ...detail.value, tradeEngineEnabled: updated.tradeEngineEnabled };
    positions.value = positions.value.map(row => row.id === positionId ? { ...row, tradeEngineEnabled: updated.tradeEngineEnabled } : row);
    await loadEngine();
  } catch (err) {
    if (!stopped && request === toggleRequest) detailError.value = getParsedApiError(err);
  } finally {
    if (!stopped && request === toggleRequest) toggleSaving.value = false;
  }
}

function onTradeEngineChange(event: Event) {
  const target = event.target as HTMLInputElement;
  const enabled = target.checked;
  target.checked = detail.value?.tradeEngineEnabled !== false;
  void toggleTradeEngine(enabled);
}

function closeDetail() {
  detailRequest++; toggleRequest++;
  detailLoading.value = false;
  toggleSaving.value = false;
  detailError.value = null;
  operations.value = [];
  markers.value = [];
  detail.value = null;
}
</script>

<template>
  <div class="space-y-6 p-4 sm:p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold">
          投资组合
        </h1>
        <p class="text-sm text-muted-foreground">
          数据库是唯一真实持仓来源，Trade Engine 每 30 分钟给出中线建议。
        </p>
      </div>
      <div class="flex gap-2">
        <Button
          :variant="market === 'CN' ? 'default' : 'outline'"
          data-testid="market-cn"
          @click="changeMarket('CN')"
        >
          CN
        </Button>
        <Button
          :variant="market === 'US' ? 'default' : 'outline'"
          data-testid="market-us"
          @click="changeMarket('US')"
        >
          US
        </Button>
      </div>
    </div>

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
          <CardDescription>总资产</CardDescription><CardTitle data-testid="total-asset">
            {{ fmt(totalAsset) }}
          </CardTitle>
        </CardHeader>
      </Card>
      <Card>
        <CardHeader>
          <CardDescription>现金</CardDescription><CardTitle data-testid="cash">
            {{ fmt(cash) }}
          </CardTitle>
        </CardHeader>
      </Card>
      <Card><CardHeader><CardDescription>持仓市值</CardDescription><CardTitle>{{ fmt(marketValue) }}</CardTitle></CardHeader></Card>
      <Card><CardHeader><CardDescription>总仓位</CardDescription><CardTitle>{{ exposure ? `${(Number(exposure) * 100).toFixed(1)}%` : '-' }}</CardTitle></CardHeader></Card>
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
              <TableHead>股票</TableHead>
              <TableHead>现价</TableHead>
              <TableHead>数量（股）</TableHead>
              <TableHead>平均成本</TableHead>
              <TableHead>市值</TableHead>
              <TableHead>仓位</TableHead>
              <TableHead>盈亏</TableHead>
              <TableHead>Trade Engine</TableHead>
              <TableHead>操作</TableHead>
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

    <Dialog
      :open="!!detail"
      @update:open="value => { if (!value) closeDetail(); }"
    >
      <DialogContent class="max-h-[calc(100dvh-2rem)] sm:max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{{ detail?.symbol }}</DialogTitle>
          <DialogDescription>当前持仓、Trade Engine 状态与操作记录</DialogDescription>
        </DialogHeader>
        <div
          v-if="detail"
          class="space-y-4"
        >
          <p>数量 {{ fmt(detail.quantity) }} · 成本 {{ fmt(detail.averageCost) }} · 市值 {{ fmt(detail.marketValue) }}</p>
          <label class="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              class="mt-1"
              data-testid="trade-engine-enabled"
              :checked="detail.tradeEngineEnabled !== false"
              :disabled="toggleSaving"
              @change="onTradeEngineChange($event)"
            />
            <span>
              <span class="font-medium">交易提醒</span>
              <span class="mt-1 block text-xs text-muted-foreground">关闭后，该持仓不运行 Strategy，系统也不会主动给出调仓指令，但仍计入账户 NAV 与组合风险。</span>
            </span>
          </label>
          <ApiErrorAlert
            v-if="detailError"
            :error="detailError"
          />
          <Button
            v-if="detailError"
            variant="outline"
            @click="openDetail(detail)"
          >
            重试详情
          </Button>
          <p
            v-if="engineError"
            class="text-sm text-destructive"
          >
            Trade Engine 建议读取失败，请重试。
          </p>
          <Button
            v-if="engineError"
            variant="outline"
            @click="loadEngine"
          >
            重试建议
          </Button>
          <p
            v-if="engineLoading"
            class="text-sm text-muted-foreground"
          >
            正在加载建议…
          </p>
          <p v-if="!engineError && !engineLoading">
            适用策略 {{ (engineView?.strategies || ['exit_v1', 'add_v1']).join(' / ') }} · 允许 Trade Engine {{ detail.tradeEngineEnabled === false ? '关闭' : '开启' }}
          </p>
          <p v-if="!engineError && !engineLoading">
            最新正式信号 {{ engineView?.action || '-' }} · 保护价 {{ engineView?.activeStop || '-' }} · 阶段 {{ engineView?.profitStage || '-' }}
          </p>
          <p v-if="engineView?.llmReason">
            LLM最终判断 {{ engineView.llmReason }}
          </p>
          <ResearchEvidence
            :key="detail.id"
            :symbol="detail.symbol"
            :market="detail.market"
            :position-id="detail.id"
          />
          <DailyKLineCard
            :key="detail.id"
            :symbol="detail.symbol"
            :markers="markers"
            marker-caption="操作 BST"
          />
          <div>
            <h3 class="mb-2 text-sm font-semibold">
              操作记录
            </h3>
            <p
              v-if="detailLoading"
              class="text-sm text-muted-foreground"
            >
              正在加载操作记录…
            </p>
            <p
              v-else-if="!detailError && !operations.length"
              class="text-sm text-muted-foreground"
            >
              暂无操作记录
            </p>
            <p
              v-for="item in operations"
              :key="item.executedAt + item.side"
            >
              {{ item.executedAt }} {{ item.side }} {{ item.quantity }} @{{ item.price }}
            </p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>
