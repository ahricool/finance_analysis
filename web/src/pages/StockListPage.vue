<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import {
  portfolioApi,
  type PortfolioAccount,
  type PortfolioAssetType,
  type PortfolioMarket,
  type PortfolioPosition,
  type PositionStatus,
} from '@/api/portfolio';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import LoadingButton from '@/components/app/LoadingButton.vue';
import ConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import AppDateTimePicker from '@/components/app/AppDateTimePicker.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import StockAutocomplete from '@/components/StockAutocomplete/StockAutocomplete.vue';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useRealtimeQuotes } from '@/composables/useRealtimeQuotes';
import type { AssetType, Market } from '@/types/stockIndex';
import { formatDecimalText, formatMarketCurrencyAmount } from '@/utils/marketCurrency';
import { BriefcaseBusiness, Pencil, Plus, Trash2 } from 'lucide-vue-next';
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

type AssetFilter = PortfolioAssetType | 'ALL';
type CreateAssetType = 'STOCK' | 'ETF' | 'OPTION';
type EquityAssetType = Exclude<CreateAssetType, 'OPTION'>;
type DialogMode = 'create' | 'edit' | null;
type PositionDirection = 'LONG' | 'SHORT';

interface SelectedSecurity {
  canonicalCode: string;
  displayCode: string;
  name: string;
  market: PortfolioMarket;
}

const ACCOUNT_ORDER: PortfolioMarket[] = ['CN', 'HK', 'US'];
const DECIMAL_PATTERN = /^\d+(?:\.\d+)?$/;
const POSITIVE_INTEGER_PATTERN = /^[1-9]\d*$/;

const route = useRoute();
const router = useRouter();
const { getQuote } = useRealtimeQuotes();
const accounts = ref<PortfolioAccount[]>([]);
const positions = ref<PortfolioPosition[]>([]);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const selectedAccountCode = ref<PortfolioMarket>('CN');
const assetFilter = ref<AssetFilter>('ALL');
const statusFilter = ref<PositionStatus | 'ALL'>('OPEN');
const dialogMode = ref<DialogMode>(null);
const editingPosition = ref<PortfolioPosition | null>(null);
const deletingPosition = ref<PortfolioPosition | null>(null);
const saving = ref(false);
const formError = ref<string | null>(null);

const stockQuery = ref('');
const selectedSecurity = ref<SelectedSecurity | null>(null);
const createAssetType = ref<CreateAssetType>('STOCK');
const optionUnderlyingType = ref<EquityAssetType>('STOCK');
const quantity = ref('');
const avgCost = ref('');
const openedAt = ref('');
const notes = ref('');
const editStatus = ref<PositionStatus>('OPEN');
const optionType = ref<'CALL' | 'PUT'>('CALL');
const expirationDate = ref('');
const strikePrice = ref('');
const optionContracts = ref('');
const optionDirection = ref<PositionDirection>('LONG');
const cashInput = ref('');
const cashSaving = ref(false);

const selectedAccount = computed(
  () => accounts.value.find((item) => item.account_code === selectedAccountCode.value) ?? null,
);
const filteredPositions = computed(() =>
  positions.value.filter(
    (item) =>
      (assetFilter.value === 'ALL' || item.asset_type === assetFilter.value) &&
      (statusFilter.value === 'ALL' || item.status === statusFilter.value),
  ),
);
const equityPositions = computed(() =>
  filteredPositions.value.filter(
    (item) => item.asset_type === 'STOCK' || item.asset_type === 'ETF',
  ),
);
const optionPositions = computed(() =>
  filteredPositions.value.filter((item) => item.asset_type === 'OPTION'),
);
const openEquities = computed(() =>
  positions.value.filter(
    (item) => item.status === 'OPEN' && (item.asset_type === 'STOCK' || item.asset_type === 'ETF'),
  ),
);
const openOptions = computed(() =>
  positions.value.filter((item) => item.status === 'OPEN' && item.asset_type === 'OPTION'),
);
const equityCost = computed(() => sumNumbers(openEquities.value.map((item) => item.cost_amount)));
const optionCost = computed(() => sumNumbers(openOptions.value.map((item) => item.cost_amount)));
const pricedEquityValues = computed(() =>
  openEquities.value.map((item) => {
    const price = getQuote(item.display_symbol, item.market)?.last_price;
    return price === null || price === undefined ? null : Number(item.quantity) * price;
  }),
);
const hasUnpricedEquity = computed(() => pricedEquityValues.value.some((value) => value === null));
const equityMarketValue = computed(() =>
  hasUnpricedEquity.value ? null : sumNumbers(pricedEquityValues.value as number[]),
);
const unrealizedPnl = computed(() =>
  equityMarketValue.value === null ? null : equityMarketValue.value - equityCost.value,
);
const pricedAssets = computed(() => {
  if (equityMarketValue.value === null || !selectedAccount.value) return null;
  return Number(selectedAccount.value.cash_balance) + equityMarketValue.value;
});
const availableAssetFilters = computed<{ value: AssetFilter; label: string }[]>(() => [
  { value: 'ALL', label: '全部' },
  { value: 'STOCK', label: '股票' },
  { value: 'ETF', label: 'ETF' },
  ...(selectedAccountCode.value === 'US' ? [{ value: 'OPTION' as const, label: '期权' }] : []),
]);
const availableCreateAssetTypes = computed<{ value: CreateAssetType; label: string }[]>(() => [
  { value: 'STOCK', label: '股票' },
  { value: 'ETF', label: 'ETF' },
  ...(selectedAccountCode.value === 'US' ? [{ value: 'OPTION' as const, label: '期权' }] : []),
]);

function sumNumbers(values: Array<string | number>): number {
  return values.reduce<number>((sum, value) => sum + Number(value), 0);
}

function amount(value: string | number | null): string {
  return formatMarketCurrencyAmount(value, selectedAccount.value?.market);
}

function toDatetimeLocal(value: string | null): string {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
}

function toIso(value: string): string | null {
  if (!value.trim()) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

function quotePrice(position: PortfolioPosition): number | null {
  return getQuote(position.display_symbol, position.market)?.last_price ?? null;
}

function positionMarketValue(position: PortfolioPosition): number | null {
  const price = quotePrice(position);
  return price === null ? null : Number(position.quantity) * price;
}

function positionPnl(position: PortfolioPosition): number | null {
  const marketValue = positionMarketValue(position);
  return marketValue === null ? null : marketValue - Number(position.cost_amount);
}

function resetForm(): void {
  stockQuery.value = '';
  selectedSecurity.value = null;
  createAssetType.value = 'STOCK';
  optionUnderlyingType.value = 'STOCK';
  quantity.value = '';
  avgCost.value = '';
  openedAt.value = '';
  notes.value = '';
  editStatus.value = 'OPEN';
  optionType.value = 'CALL';
  expirationDate.value = '';
  strikePrice.value = '';
  optionContracts.value = '';
  optionDirection.value = 'LONG';
  formError.value = null;
}

function openCreatePosition(): void {
  resetForm();
  dialogMode.value = 'create';
}

function changeCreateAssetType(assetType: CreateAssetType): void {
  if (assetType === 'OPTION' && selectedAccountCode.value !== 'US') return;
  resetForm();
  createAssetType.value = assetType;
  dialogMode.value = 'create';
}

function openEdit(position: PortfolioPosition): void {
  resetForm();
  editingPosition.value = position;
  quantity.value = position.quantity.replace(/^-/, '');
  optionContracts.value = quantity.value;
  optionDirection.value = position.position_side;
  avgCost.value = position.avg_cost;
  openedAt.value = toDatetimeLocal(position.opened_at);
  notes.value = position.notes ?? '';
  editStatus.value = position.status;
  dialogMode.value = 'edit';
}

function closeDialog(): void {
  dialogMode.value = null;
  editingPosition.value = null;
}

function handleAutocompleteInput(value: string): void {
  stockQuery.value = value;
  selectedSecurity.value = null;
  formError.value = null;
}

function handleAutocomplete(
  canonicalCode: string,
  name?: string,
  source?: 'manual' | 'autocomplete',
  market?: Market,
  assetType?: AssetType,
): void {
  selectedSecurity.value = null;
  if (source !== 'autocomplete' || !selectedAccount.value) {
    formError.value = '请从搜索结果中选择标的';
    return;
  }
  const normalizedMarket: PortfolioMarket | null =
    market === 'BSE' ? 'CN' : market === 'CN' || market === 'HK' || market === 'US' ? market : null;
  if (normalizedMarket !== selectedAccount.value.market) {
    formError.value = `只能选择${selectedAccount.value.name}对应市场的标的`;
    return;
  }
  if (assetType === 'index') {
    formError.value = '仅支持股票和 ETF';
    return;
  }
  const displayCode = canonicalCode.split('.')[0] ?? canonicalCode;
  selectedSecurity.value = {
    canonicalCode,
    displayCode,
    name: name ?? '',
    market: normalizedMarket,
  };
  stockQuery.value = name ? `${name}（${displayCode}）` : displayCode;
  formError.value = null;
}

function validNonNegativeDecimal(value: string): boolean {
  return DECIMAL_PATTERN.test(value.trim());
}

function validateCommon(): string | null {
  if (!selectedSecurity.value) return '请从搜索结果中选择标的';
  if (!validNonNegativeDecimal(avgCost.value)) return '平均成本必须是大于等于 0 的数字';
  if (openedAt.value && toIso(openedAt.value) === null) return '建仓时间格式不正确';
  return null;
}

async function savePosition(): Promise<void> {
  formError.value = null;
  const account = selectedAccount.value;
  if (!account) return;
  saving.value = true;
  try {
    if (dialogMode.value === 'edit' && editingPosition.value) {
      const position = editingPosition.value;
      const rawQuantity = position.asset_type === 'OPTION' ? optionContracts.value : quantity.value;
      if (
        (position.asset_type === 'OPTION' && !POSITIVE_INTEGER_PATTERN.test(rawQuantity)) ||
        (position.asset_type !== 'OPTION' &&
          (!validNonNegativeDecimal(rawQuantity) || Number(rawQuantity) <= 0))
      ) {
        formError.value = position.asset_type === 'OPTION' ? '张数必须为正整数' : '数量必须大于 0';
        return;
      }
      if (!validNonNegativeDecimal(avgCost.value)) {
        formError.value = '平均成本必须是大于等于 0 的数字';
        return;
      }
      const signedQuantity =
        position.asset_type === 'OPTION' && optionDirection.value === 'SHORT'
          ? `-${rawQuantity}`
          : rawQuantity;
      await portfolioApi.updatePosition(position.id, {
        quantity: signedQuantity,
        avg_cost: avgCost.value.trim(),
        opened_at: toIso(openedAt.value),
        status: editStatus.value,
        notes: notes.value.trim() || null,
      });
    } else if (dialogMode.value === 'create' && createAssetType.value !== 'OPTION') {
      const validation = validateCommon();
      if (validation || !validNonNegativeDecimal(quantity.value) || Number(quantity.value) <= 0) {
        formError.value = validation ?? '数量必须大于 0';
        return;
      }
      await portfolioApi.createEquity(account.id, {
        canonical_symbol: selectedSecurity.value!.canonicalCode,
        display_symbol: selectedSecurity.value!.displayCode,
        name: selectedSecurity.value!.name || undefined,
        asset_type: createAssetType.value,
        quantity: quantity.value.trim(),
        avg_cost: avgCost.value.trim(),
        opened_at: toIso(openedAt.value),
        notes: notes.value.trim() || null,
      });
    } else if (dialogMode.value === 'create' && createAssetType.value === 'OPTION') {
      const validation = validateCommon();
      if (validation) {
        formError.value = validation;
        return;
      }
      if (!expirationDate.value) formError.value = '请选择到期日';
      else if (!validNonNegativeDecimal(strikePrice.value) || Number(strikePrice.value) <= 0)
        formError.value = '行权价必须大于 0';
      else if (!POSITIVE_INTEGER_PATTERN.test(optionContracts.value))
        formError.value = '张数必须为正整数';
      if (formError.value) return;
      const signedQuantity =
        optionDirection.value === 'SHORT' ? `-${optionContracts.value}` : optionContracts.value;
      await portfolioApi.createOption(account.id, {
        underlying_canonical_symbol: selectedSecurity.value!.canonicalCode,
        underlying_display_symbol: selectedSecurity.value!.displayCode,
        underlying_name: selectedSecurity.value!.name || undefined,
        underlying_asset_type: optionUnderlyingType.value,
        option_type: optionType.value,
        expiration_date: expirationDate.value,
        strike_price: strikePrice.value.trim(),
        quantity: signedQuantity,
        avg_cost: avgCost.value.trim(),
        contract_multiplier: '100',
        opened_at: toIso(openedAt.value),
        notes: notes.value.trim() || null,
      });
    }
    closeDialog();
    await loadPositions();
  } catch (caught) {
    formError.value = getParsedApiError(caught).message;
  } finally {
    saving.value = false;
  }
}

async function loadPositions(): Promise<void> {
  const account = selectedAccount.value;
  if (!account) return;
  loading.value = true;
  error.value = null;
  try {
    positions.value = await portfolioApi.listPositions(account.id, 'ALL', 'ALL');
    cashInput.value = account.cash_balance;
  } catch (caught) {
    error.value = getParsedApiError(caught);
  } finally {
    loading.value = false;
  }
}

async function selectAccount(code: PortfolioMarket): Promise<void> {
  selectedAccountCode.value = code;
  assetFilter.value = 'ALL';
  await router.replace({ query: { ...route.query, account: code } });
  await loadPositions();
}

async function saveCash(): Promise<void> {
  const account = selectedAccount.value;
  if (!account || !/^-?\d+(?:\.\d+)?$/.test(cashInput.value.trim())) {
    error.value = getParsedApiError(new Error('现金余额格式不正确'));
    return;
  }
  cashSaving.value = true;
  try {
    const updated = await portfolioApi.updateCash(account.id, cashInput.value.trim());
    const index = accounts.value.findIndex((item) => item.id === updated.id);
    if (index >= 0) accounts.value[index] = updated;
  } catch (caught) {
    error.value = getParsedApiError(caught);
  } finally {
    cashSaving.value = false;
  }
}

async function confirmDelete(): Promise<void> {
  if (!deletingPosition.value) return;
  try {
    await portfolioApi.removePosition(deletingPosition.value.id);
    deletingPosition.value = null;
    await loadPositions();
  } catch (caught) {
    error.value = getParsedApiError(caught);
  }
}

async function markStatus(
  position: PortfolioPosition,
  status: 'CLOSED' | 'EXPIRED',
): Promise<void> {
  try {
    await portfolioApi.updatePosition(position.id, { status });
    await loadPositions();
  } catch (caught) {
    error.value = getParsedApiError(caught);
  }
}

function dteLabel(position: PortfolioPosition): string {
  const dte = position.option?.days_to_expiration;
  if (dte === undefined) return '—';
  if (dte < 0 && position.status === 'OPEN') return '已到期，待确认处理';
  if (dte === 0) return '今日到期';
  return `${dte} 天`;
}

function dteClass(position: PortfolioPosition): string {
  const dte = position.option?.days_to_expiration;
  if (dte === undefined || dte > 7) return 'text-muted-foreground';
  if (dte >= 1) return 'text-amber-500';
  return 'text-red-500';
}

watch(selectedAccountCode, () => {
  if (selectedAccountCode.value !== 'US' && assetFilter.value === 'OPTION')
    assetFilter.value = 'ALL';
});

onMounted(async () => {
  loading.value = true;
  try {
    accounts.value = (await portfolioApi.listAccounts()).sort(
      (left, right) =>
        ACCOUNT_ORDER.indexOf(left.account_code) - ACCOUNT_ORDER.indexOf(right.account_code),
    );
    const queryAccount = String(route.query.account ?? '').toUpperCase();
    selectedAccountCode.value = ACCOUNT_ORDER.includes(queryAccount as PortfolioMarket)
      ? (queryAccount as PortfolioMarket)
      : 'CN';
    await loadPositions();
  } catch (caught) {
    error.value = getParsedApiError(caught);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div
    class="space-y-5"
    data-testid="portfolio-page"
  >
    <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <div class="flex items-center gap-2">
          <BriefcaseBusiness class="h-5 w-5 text-primary" />
          <h2 class="text-xl font-semibold text-foreground">
            投资组合
          </h2>
        </div>
        <p class="mt-1 text-sm text-muted-foreground">
          按市场管理固定账户的现金、股票、ETF 与美股期权记录。
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button
          data-testid="add-position"
          size="sm"
          @click="openCreatePosition"
        >
          <Plus class="h-4 w-4" />添加持仓
        </Button>
      </div>
    </div>

    <ApiErrorAlert
      v-if="error"
      :error="error"
      @dismiss="error = null"
    />

    <Tabs
      :model-value="selectedAccountCode"
    >
      <TabsList class="grid h-auto w-full grid-cols-3">
        <TabsTrigger
          v-for="account in accounts"
          :key="account.account_code"
          :value="account.account_code"
          :data-account-code="account.account_code"
          @click="selectAccount(account.account_code)"
        >
          {{ account.name }}
        </TabsTrigger>
      </TabsList>
    </Tabs>

    <section
      v-if="selectedAccount"
      class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"
      aria-label="账户汇总"
    >
      <Card>
        <CardHeader class="pb-2">
          <CardDescription>现金余额 · {{ selectedAccount.currency }}</CardDescription>
        </CardHeader>
        <CardContent>
          <div class="flex items-center gap-2">
            <input
              v-model="cashInput"
              class="border-input bg-background shadow-xs min-w-0 flex-1 rounded-lg px-2 py-1.5 text-sm"
              aria-label="现金余额"
            />
            <LoadingButton
              size="xs"
              :loading="cashSaving"
              @click="saveCash"
            >
              保存
            </LoadingButton>
          </div>
        </CardContent>
      </Card>
      <Card><CardHeader><CardDescription>股票/ETF 持仓成本</CardDescription><CardTitle>{{ amount(equityCost) }}</CardTitle></CardHeader></Card>
      <Card>
        <CardHeader><CardDescription>股票/ETF 实时市值</CardDescription><CardTitle>{{ amount(equityMarketValue) }}</CardTitle></CardHeader><CardContent
          v-if="hasUnpricedEquity"
          class="text-xs text-warning"
        >
          存在未定价股票/ETF
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardDescription>股票/ETF 未实现盈亏</CardDescription><CardTitle
            :class="unrealizedPnl !== null && unrealizedPnl < 0 ? 'text-emerald-500' : 'text-red-500'"
          >
            {{ amount(unrealizedPnl) }}
          </CardTitle>
        </CardHeader>
      </Card>
      <Card>
        <CardHeader><CardDescription>可定价资产 · 不含期权</CardDescription><CardTitle>{{ amount(pricedAssets) }}</CardTitle></CardHeader><CardContent
          v-if="selectedAccountCode === 'US'"
          class="text-xs text-muted-foreground"
        >
          期权 {{ openOptions.length }} 笔 · 成本 {{ amount(optionCost) }}
        </CardContent>
      </Card>
    </section>

    <div class="flex flex-wrap items-center gap-2">
      <Button
        v-for="option in availableAssetFilters"
        :key="option.value"
        size="sm"
        :variant="assetFilter === option.value ? 'secondary' : 'ghost'"
        @click="assetFilter = option.value"
      >
        {{ option.label }}
      </Button>
      <FieldSelect
        :model-value="statusFilter"
        class="ml-auto min-w-32"
        :options="[
          { value: 'OPEN', label: '持有中' },
          { value: 'CLOSED', label: '已平仓' },
          { value: 'EXPIRED', label: '已失效' },
          { value: 'ALL', label: '全部状态' },
        ]"
        @update:model-value="statusFilter = $event as PositionStatus | 'ALL'"
      />
    </div>

    <div
      v-if="loading"
      class="space-y-3"
    >
      <Skeleton
        v-for="index in 5"
        :key="index"
        class="h-16 w-full"
      />
    </div>
    <template v-else>
      <section
        v-if="equityPositions.length"
        data-testid="equity-section"
      >
        <div class="hidden overflow-hidden rounded-2xl border border-border/70 bg-card md:block">
          <table class="w-full text-sm">
            <thead class="bg-muted/40 text-left text-xs text-muted-foreground">
              <tr>
                <th class="p-3">
                  标的
                </th>
                <th>类型</th>
                <th>数量</th>
                <th>最新价格</th>
                <th>平均成本</th>
                <th>成本金额</th>
                <th>持仓市值</th>
                <th>未实现盈亏</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border/60">
              <tr
                v-for="position in equityPositions"
                :key="position.id"
              >
                <td class="p-3">
                  <p class="font-medium">
                    {{ position.display_symbol }}
                  </p>
                  <p class="text-xs text-muted-foreground">
                    {{ position.name || '—' }}
                  </p>
                </td>
                <td>{{ position.asset_type === 'ETF' ? 'ETF' : '股票' }}</td>
                <td>{{ formatDecimalText(position.quantity) }} 股</td>
                <td>{{ quotePrice(position) === null ? '—' : amount(quotePrice(position)) }}</td>
                <td>{{ amount(position.avg_cost) }}</td>
                <td>{{ amount(position.cost_amount) }}</td>
                <td>{{ amount(positionMarketValue(position)) }}</td>
                <td>{{ amount(positionPnl(position)) }}</td>
                <td>
                  <div class="flex gap-1">
                    <Button
                      variant="ghost"
                      size="xs"
                      aria-label="编辑持仓"
                      @click="openEdit(position)"
                    >
                      <Pencil class="h-3.5 w-3.5" />
                    </Button><Button
                      variant="destructive"
                      size="xs"
                      aria-label="删除持仓"
                      @click="deletingPosition = position"
                    >
                      <Trash2 class="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="grid gap-3 md:hidden">
          <article
            v-for="position in equityPositions"
            :key="position.id"
            class="rounded-2xl border border-border/70 bg-card p-4"
          >
            <div class="flex justify-between">
              <div>
                <p class="font-semibold">
                  {{ position.display_symbol }} · {{ position.name }}
                </p>
                <p class="text-xs text-primary">
                  {{ position.asset_type }}
                </p>
              </div>
              <div class="flex gap-1">
                <button
                  aria-label="编辑持仓"
                  @click="openEdit(position)"
                >
                  <Pencil class="h-4 w-4" />
                </button><button
                  aria-label="删除持仓"
                  @click="deletingPosition = position"
                >
                  <Trash2 class="h-4 w-4 text-red-500" />
                </button>
              </div>
            </div>
            <dl class="mt-3 grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt class="text-xs text-muted-foreground">
                  数量
                </dt>
                <dd>{{ formatDecimalText(position.quantity) }} 股</dd>
              </div>
              <div>
                <dt class="text-xs text-muted-foreground">
                  最新价格
                </dt>
                <dd>{{ amount(quotePrice(position)) }}</dd>
              </div>
              <div>
                <dt class="text-xs text-muted-foreground">
                  市值
                </dt>
                <dd>{{ amount(positionMarketValue(position)) }}</dd>
              </div>
              <div>
                <dt class="text-xs text-muted-foreground">
                  未实现盈亏
                </dt>
                <dd>{{ amount(positionPnl(position)) }}</dd>
              </div>
            </dl>
          </article>
        </div>
      </section>

      <section
        v-if="selectedAccountCode === 'US' && optionPositions.length"
        data-testid="option-section"
        class="space-y-3"
      >
        <p class="rounded-xl border border-amber-500/25 bg-amber-500/10 p-3 text-xs text-amber-500">
          期权仅作手工持仓记录，不提供实时价格、市值或盈亏。
        </p>
        <div class="hidden overflow-hidden rounded-2xl border border-border/70 bg-card md:block">
          <table class="w-full text-sm">
            <thead class="bg-muted/40 text-left text-xs text-muted-foreground">
              <tr>
                <th class="p-3">
                  标的
                </th>
                <th>方向</th>
                <th>Call/Put</th>
                <th>行权价</th>
                <th>到期日 / DTE</th>
                <th>张数</th>
                <th>平均成本</th>
                <th>乘数</th>
                <th>成本金额</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border/60">
              <tr
                v-for="position in optionPositions"
                :key="position.id"
              >
                <td class="p-3">
                  {{ position.option?.underlying_display_symbol }}
                </td>
                <td>{{ position.position_side === 'LONG' ? '多头' : '空头' }}</td>
                <td>{{ position.option?.option_type === 'CALL' ? 'Call' : 'Put' }}</td>
                <td>{{ amount(position.option?.strike_price ?? null) }}</td>
                <td>
                  {{ position.option?.expiration_date }}
                  <p
                    :class="dteClass(position)"
                    class="text-xs"
                  >
                    {{ dteLabel(position) }}
                  </p>
                </td>
                <td>{{ formatDecimalText(position.quantity.replace('-', '')) }} 张</td>
                <td>{{ amount(position.avg_cost) }}</td>
                <td>{{ formatDecimalText(position.contract_multiplier) }}</td>
                <td>{{ amount(position.cost_amount) }}</td>
                <td>{{ position.status }}</td>
                <td>
                  <div class="flex gap-1">
                    <Button
                      v-if="position.option?.expiration_action_required"
                      variant="ghost"
                      size="xs"
                      @click="markStatus(position, 'CLOSED')"
                    >
                      标记已平仓
                    </Button><Button
                      v-if="position.option?.expiration_action_required"
                      variant="ghost"
                      size="xs"
                      @click="markStatus(position, 'EXPIRED')"
                    >
                      标记失效
                    </Button><Button
                      variant="ghost"
                      size="xs"
                      aria-label="编辑期权"
                      @click="openEdit(position)"
                    >
                      <Pencil class="h-3.5 w-3.5" />
                    </Button><Button
                      variant="destructive"
                      size="xs"
                      aria-label="删除期权"
                      @click="deletingPosition = position"
                    >
                      <Trash2 class="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="grid gap-3 md:hidden">
          <article
            v-for="position in optionPositions"
            :key="position.id"
            class="rounded-2xl border border-border/70 bg-card p-4"
          >
            <div class="flex justify-between">
              <div>
                <p class="font-semibold">
                  {{ position.option?.underlying_display_symbol }}
                </p>
                <p class="text-xs text-amber-500">
                  {{ position.position_side === 'LONG' ? '多头' : '空头' }} ·
                  {{ position.option?.option_type }}
                </p>
              </div>
              <div class="flex gap-2">
                <button
                  aria-label="编辑期权"
                  @click="openEdit(position)"
                >
                  <Pencil class="h-4 w-4" />
                </button><button
                  aria-label="删除期权"
                  @click="deletingPosition = position"
                >
                  <Trash2 class="h-4 w-4 text-red-500" />
                </button>
              </div>
            </div>
            <dl class="mt-3 grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt class="text-xs text-muted-foreground">
                  行权价
                </dt>
                <dd>{{ amount(position.option?.strike_price ?? null) }}</dd>
              </div>
              <div>
                <dt class="text-xs text-muted-foreground">
                  到期日 / DTE
                </dt>
                <dd>
                  {{ position.option?.expiration_date }} ·
                  <span :class="dteClass(position)">{{ dteLabel(position) }}</span>
                </dd>
              </div>
              <div>
                <dt class="text-xs text-muted-foreground">
                  张数
                </dt>
                <dd>{{ formatDecimalText(position.quantity.replace('-', '')) }}</dd>
              </div>
              <div>
                <dt class="text-xs text-muted-foreground">
                  成本金额
                </dt>
                <dd>{{ amount(position.cost_amount) }}</dd>
              </div>
              <div>
                <dt class="text-xs text-muted-foreground">
                  状态
                </dt>
                <dd>{{ position.status }}</dd>
              </div>
            </dl>
            <div
              v-if="position.option?.expiration_action_required"
              class="mt-3 flex gap-2"
            >
              <Button
                size="xs"
                variant="secondary"
                @click="markStatus(position, 'CLOSED')"
              >
                标记已平仓
              </Button><Button
                size="xs"
                variant="destructive"
                @click="markStatus(position, 'EXPIRED')"
              >
                标记到期失效
              </Button>
            </div>
          </article>
        </div>
      </section>
      <Empty
        v-if="!filteredPositions.length"
      >
        <EmptyHeader><EmptyTitle>暂无持仓记录</EmptyTitle><EmptyDescription>当前账户和筛选条件下没有可展示的持仓。</EmptyDescription></EmptyHeader>
      </Empty>
    </template>

    <Dialog
      :open="dialogMode !== null"
      @update:open="closeDialog"
    >
      <DialogContent class="max-h-[calc(100dvh-1rem)] max-w-xl overflow-y-auto">
        <DialogHeader><DialogTitle>{{ dialogMode === 'edit' ? '编辑持仓' : '添加持仓' }}</DialogTitle><DialogDescription>维护标的、数量、成本、建仓时间和持仓状态。</DialogDescription></DialogHeader>
        <form
          class="space-y-4"
          @submit.prevent="savePosition"
        >
          <template v-if="dialogMode !== 'edit'">
            <fieldset>
              <legend class="text-sm font-medium">
                持仓类型
              </legend>
              <div class="mt-2 flex flex-wrap gap-4">
                <label
                  v-for="assetType in availableCreateAssetTypes"
                  :key="assetType.value"
                  class="flex items-center gap-2 text-sm"
                >
                  <input
                    :checked="createAssetType === assetType.value"
                    :data-create-asset-type="assetType.value"
                    type="radio"
                    name="create-asset-type"
                    :value="assetType.value"
                    @change="changeCreateAssetType(assetType.value)"
                  />
                  {{ assetType.label }}
                </label>
              </div>
            </fieldset>
            <fieldset v-if="createAssetType === 'OPTION'">
              <legend class="text-sm font-medium">
                标的类型
              </legend>
              <div class="mt-2 flex gap-4">
                <label class="flex items-center gap-2 text-sm">
                  <input
                    v-model="optionUnderlyingType"
                    type="radio"
                    name="option-underlying-type"
                    value="STOCK"
                  />股票
                </label>
                <label class="flex items-center gap-2 text-sm">
                  <input
                    v-model="optionUnderlyingType"
                    type="radio"
                    name="option-underlying-type"
                    value="ETF"
                  />ETF
                </label>
              </div>
            </fieldset>
            <label class="block text-sm font-medium">{{
              createAssetType === 'OPTION' ? '期权标的' : '标的'
            }}</label>
            <StockAutocomplete
              :model-value="stockQuery"
              :placeholder="`搜索${selectedAccount?.name ?? ''}标的`"
              @update:model-value="handleAutocompleteInput"
              @submit="handleAutocomplete"
            />
            <p
              v-if="selectedSecurity"
              class="text-xs text-primary"
            >
              已选择 {{ selectedSecurity.canonicalCode }} ·
              {{ createAssetType === 'OPTION' ? optionUnderlyingType : createAssetType }}
            </p>
          </template>
          <template v-if="dialogMode === 'create' && createAssetType === 'OPTION'">
            <div class="grid gap-3 sm:grid-cols-2">
              <FieldSelect
                v-model="optionType"
                label="Call / Put"
                :options="[
                  { value: 'CALL', label: 'Call' },
                  { value: 'PUT', label: 'Put' },
                ]"
              /><AppDatePicker
                v-model="expirationDate"
                label="到期日"
              />
            </div>
            <div class="grid grid-cols-2 items-end gap-3">
              <FieldInput
                v-model="strikePrice"
                label="行权价"
                inputmode="decimal"
              />
              <p
                class="rounded-xl border border-border/70 bg-muted/30 px-3 py-2 text-sm text-muted-foreground"
              >
                合约乘数：100
              </p>
            </div>
            <div class="grid gap-3 sm:grid-cols-2">
              <FieldInput
                v-model="optionContracts"
                label="张数"
                inputmode="numeric"
              /><FieldSelect
                :model-value="optionDirection"
                label="持仓方向"
                :options="[
                  { value: 'LONG', label: '多头' },
                  { value: 'SHORT', label: '空头' },
                ]"
                @update:model-value="optionDirection = $event as PositionDirection"
              />
            </div>
          </template>
          <template v-else-if="dialogMode === 'edit' && editingPosition?.asset_type === 'OPTION'">
            <div class="grid gap-3 sm:grid-cols-2">
              <FieldInput
                v-model="optionContracts"
                label="张数"
                inputmode="numeric"
              /><FieldSelect
                :model-value="optionDirection"
                label="持仓方向"
                :options="[
                  { value: 'LONG', label: '多头' },
                  { value: 'SHORT', label: '空头' },
                ]"
                @update:model-value="optionDirection = $event as PositionDirection"
              />
            </div>
          </template>
          <FieldInput
            v-else
            v-model="quantity"
            label="数量"
            inputmode="decimal"
          />
          <FieldInput
            v-model="avgCost"
            label="平均成本"
            inputmode="decimal"
          />
          <AppDateTimePicker
            v-model="openedAt"
            label="建仓时间"
          />
          <FieldSelect
            v-if="dialogMode === 'edit'"
            :model-value="editStatus"
            label="状态"
            :options="[
              { value: 'OPEN', label: 'OPEN' },
              { value: 'CLOSED', label: 'CLOSED' },
              ...(editingPosition?.asset_type === 'OPTION'
                ? [{ value: 'EXPIRED', label: 'EXPIRED' }]
                : []),
            ]"
            @update:model-value="editStatus = $event as PositionStatus"
          />
          <label class="grid gap-2 text-sm">备注<Textarea
            v-model="notes"
            class="min-h-20"
          /></label>
          <p
            v-if="formError"
            class="text-sm text-red-500"
          >
            {{ formError }}
          </p>
          <DialogFooter>
            <Button
              variant="secondary"
              @click="closeDialog"
            >
              取消
            </Button><LoadingButton
              type="submit"
              :loading="saving"
            >
              保存
            </LoadingButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
    <ConfirmDialog
      :open="deletingPosition !== null"
      title="删除持仓记录"
      :description="`确认删除 ${deletingPosition?.display_symbol ?? ''}？此操作不可撤销。`"
      confirm-text="删除"
      destructive
      @update:open="deletingPosition = null"
      @confirm="confirmDelete"
    />
  </div>
</template>
