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
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Button from '@/components/common/Button.vue';
import ConfirmDialog from '@/components/common/ConfirmDialog.vue';
import Dialog from '@/components/common/Dialog.vue';
import Input from '@/components/common/Input.vue';
import StockAutocomplete from '@/components/StockAutocomplete/StockAutocomplete.vue';
import { useRealtimeQuotes } from '@/composables/useRealtimeQuotes';
import type { AssetType, Market } from '@/types/stockIndex';
import { formatDecimalText, formatMarketCurrencyAmount } from '@/utils/marketCurrency';
import { BriefcaseBusiness, Pencil, Plus, Trash2 } from 'lucide-vue-next';
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

type AssetFilter = PortfolioAssetType | 'ALL';
type DialogMode = 'equity' | 'option' | 'edit' | null;
type PositionDirection = 'LONG' | 'SHORT';

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
const selectedCanonical = ref('');
const selectedDisplay = ref('');
const selectedName = ref('');
const selectedUnderlyingType = ref<'STOCK' | 'ETF'>('STOCK');
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
const contractMultiplier = ref('100');
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
  filteredPositions.value.filter((item) => item.asset_type === 'STOCK' || item.asset_type === 'ETF'),
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
  return new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
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
  selectedCanonical.value = '';
  selectedDisplay.value = '';
  selectedName.value = '';
  selectedUnderlyingType.value = 'STOCK';
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
  contractMultiplier.value = '100';
  formError.value = null;
}

function openCreateEquity(): void {
  resetForm();
  dialogMode.value = 'equity';
}

function openCreateOption(): void {
  resetForm();
  dialogMode.value = 'option';
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

function handleAutocomplete(
  canonicalCode: string,
  name?: string,
  source?: 'manual' | 'autocomplete',
  market?: Market,
  assetType?: AssetType,
): void {
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
  selectedCanonical.value = canonicalCode;
  selectedDisplay.value = canonicalCode.split('.')[0] ?? canonicalCode;
  selectedName.value = name ?? '';
  selectedUnderlyingType.value = assetType === 'etf' ? 'ETF' : 'STOCK';
  stockQuery.value = name ? `${name}（${selectedDisplay.value}）` : selectedDisplay.value;
  formError.value = null;
}

function validNonNegativeDecimal(value: string): boolean {
  return DECIMAL_PATTERN.test(value.trim());
}

function validateCommon(): string | null {
  if (!selectedCanonical.value) return '请从搜索结果中选择标的';
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
        (position.asset_type !== 'OPTION' && (!validNonNegativeDecimal(rawQuantity) || Number(rawQuantity) <= 0))
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
    } else if (dialogMode.value === 'equity') {
      const validation = validateCommon();
      if (validation || !validNonNegativeDecimal(quantity.value) || Number(quantity.value) <= 0) {
        formError.value = validation ?? '数量必须大于 0';
        return;
      }
      await portfolioApi.createEquity(account.id, {
        canonical_symbol: selectedCanonical.value,
        display_symbol: selectedDisplay.value,
        name: selectedName.value || undefined,
        asset_type: selectedUnderlyingType.value,
        quantity: quantity.value.trim(),
        avg_cost: avgCost.value.trim(),
        opened_at: toIso(openedAt.value),
        notes: notes.value.trim() || null,
      });
    } else if (dialogMode.value === 'option') {
      const validation = validateCommon();
      if (validation) {
        formError.value = validation;
        return;
      }
      if (!expirationDate.value) formError.value = '请选择到期日';
      else if (!validNonNegativeDecimal(strikePrice.value) || Number(strikePrice.value) <= 0)
        formError.value = '行权价必须大于 0';
      else if (!POSITIVE_INTEGER_PATTERN.test(optionContracts.value)) formError.value = '张数必须为正整数';
      else if (!validNonNegativeDecimal(contractMultiplier.value) || Number(contractMultiplier.value) <= 0)
        formError.value = '合约乘数必须大于 0';
      if (formError.value) return;
      const signedQuantity =
        optionDirection.value === 'SHORT' ? `-${optionContracts.value}` : optionContracts.value;
      await portfolioApi.createOption(account.id, {
        underlying_canonical_symbol: selectedCanonical.value,
        underlying_display_symbol: selectedDisplay.value,
        underlying_name: selectedName.value || undefined,
        underlying_asset_type: selectedUnderlyingType.value,
        option_type: optionType.value,
        expiration_date: expirationDate.value,
        strike_price: strikePrice.value.trim(),
        quantity: signedQuantity,
        avg_cost: avgCost.value.trim(),
        contract_multiplier: contractMultiplier.value.trim(),
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

async function markStatus(position: PortfolioPosition, status: 'CLOSED' | 'EXPIRED'): Promise<void> {
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
  if (dte === undefined || dte > 7) return 'text-secondary-text';
  if (dte >= 1) return 'text-amber-500';
  return 'text-red-500';
}

watch(selectedAccountCode, () => {
  if (selectedAccountCode.value !== 'US' && assetFilter.value === 'OPTION') assetFilter.value = 'ALL';
});

onMounted(async () => {
  loading.value = true;
  try {
    accounts.value = (await portfolioApi.listAccounts()).sort(
      (left, right) => ACCOUNT_ORDER.indexOf(left.account_code) - ACCOUNT_ORDER.indexOf(right.account_code),
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
  <div class="space-y-5" data-testid="portfolio-page">
    <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <div class="flex items-center gap-2">
          <BriefcaseBusiness class="h-5 w-5 text-cyan" />
          <h2 class="text-xl font-semibold text-foreground">投资组合</h2>
        </div>
        <p class="mt-1 text-sm text-secondary-text">按市场管理固定账户的现金、股票、ETF 与美股期权记录。</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button variant="secondary" size="sm" @click="openCreateEquity">
          <Plus class="h-4 w-4" />添加股票 / ETF
        </Button>
        <Button
          v-if="selectedAccountCode === 'US'"
          data-testid="add-option"
          size="sm"
          @click="openCreateOption"
        >
          <Plus class="h-4 w-4" />添加期权
        </Button>
      </div>
    </div>

    <ApiErrorAlert v-if="error" :error="error" @dismiss="error = null" />

    <div class="grid grid-cols-3 gap-1 rounded-2xl border border-border/70 bg-card p-1" role="tablist">
      <button
        v-for="account in accounts"
        :key="account.account_code"
        type="button"
        role="tab"
        :aria-selected="selectedAccountCode === account.account_code"
        :data-account-code="account.account_code"
        class="rounded-xl px-3 py-2 text-sm font-medium transition-colors"
        :class="selectedAccountCode === account.account_code ? 'bg-primary/15 text-cyan' : 'text-secondary-text hover:bg-hover'"
        @click="selectAccount(account.account_code)"
      >
        {{ account.name }}
      </button>
    </div>

    <section v-if="selectedAccount" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="账户汇总">
      <div class="rounded-2xl border border-border/70 bg-card p-4">
        <p class="text-xs text-secondary-text">现金余额 · {{ selectedAccount.currency }}</p>
        <div class="mt-2 flex items-center gap-2">
          <input v-model="cashInput" class="input-surface min-w-0 flex-1 rounded-lg px-2 py-1.5 text-sm" aria-label="现金余额" />
          <Button size="xsm" :is-loading="cashSaving" @click="saveCash">保存</Button>
        </div>
      </div>
      <div class="rounded-2xl border border-border/70 bg-card p-4">
        <p class="text-xs text-secondary-text">股票/ETF 持仓成本</p>
        <p class="mt-2 text-lg font-semibold">{{ amount(equityCost) }}</p>
      </div>
      <div class="rounded-2xl border border-border/70 bg-card p-4">
        <p class="text-xs text-secondary-text">股票/ETF 实时市值</p>
        <p class="mt-2 text-lg font-semibold">{{ amount(equityMarketValue) }}</p>
        <p v-if="hasUnpricedEquity" class="mt-1 text-xs text-amber-500">存在未定价股票/ETF</p>
      </div>
      <div class="rounded-2xl border border-border/70 bg-card p-4">
        <p class="text-xs text-secondary-text">股票/ETF 未实现盈亏</p>
        <p class="mt-2 text-lg font-semibold" :class="unrealizedPnl !== null && unrealizedPnl < 0 ? 'text-emerald-500' : 'text-red-500'">
          {{ amount(unrealizedPnl) }}
        </p>
      </div>
      <div class="rounded-2xl border border-border/70 bg-card p-4">
        <p class="text-xs text-secondary-text">可定价资产 · 不含期权</p>
        <p class="mt-2 text-lg font-semibold">{{ amount(pricedAssets) }}</p>
        <p v-if="selectedAccountCode === 'US'" class="mt-1 text-xs text-secondary-text">
          期权 {{ openOptions.length }} 笔 · 成本 {{ amount(optionCost) }}
        </p>
      </div>
    </section>

    <div class="flex flex-wrap items-center gap-2">
      <button
        v-for="option in availableAssetFilters"
        :key="option.value"
        type="button"
        class="rounded-full border px-3 py-1.5 text-xs font-medium"
        :class="assetFilter === option.value ? 'border-cyan/40 bg-cyan/10 text-cyan' : 'border-border text-secondary-text'"
        @click="assetFilter = option.value"
      >
        {{ option.label }}
      </button>
      <select v-model="statusFilter" class="ml-auto rounded-xl border border-border bg-card px-3 py-1.5 text-xs">
        <option value="OPEN">持有中</option><option value="CLOSED">已平仓</option>
        <option value="EXPIRED">已失效</option><option value="ALL">全部状态</option>
      </select>
    </div>

    <div v-if="loading" class="rounded-2xl border border-border/70 bg-card p-10 text-center text-secondary-text">加载中...</div>
    <template v-else>
      <section v-if="equityPositions.length" data-testid="equity-section">
        <div class="hidden overflow-hidden rounded-2xl border border-border/70 bg-card md:block">
          <table class="w-full text-sm">
            <thead class="bg-muted/40 text-left text-xs text-secondary-text">
              <tr><th class="p-3">标的</th><th>类型</th><th>数量</th><th>最新价格</th><th>平均成本</th><th>成本金额</th><th>持仓市值</th><th>未实现盈亏</th><th>操作</th></tr>
            </thead>
            <tbody class="divide-y divide-border/60">
              <tr v-for="position in equityPositions" :key="position.id">
                <td class="p-3"><p class="font-medium">{{ position.display_symbol }}</p><p class="text-xs text-secondary-text">{{ position.name || '—' }}</p></td>
                <td>{{ position.asset_type === 'ETF' ? 'ETF' : '股票' }}</td>
                <td>{{ formatDecimalText(position.quantity) }} 股</td>
                <td>{{ quotePrice(position) === null ? '—' : amount(quotePrice(position)) }}</td>
                <td>{{ amount(position.avg_cost) }}</td><td>{{ amount(position.cost_amount) }}</td>
                <td>{{ amount(positionMarketValue(position)) }}</td><td>{{ amount(positionPnl(position)) }}</td>
                <td><div class="flex gap-1"><Button variant="ghost" size="xsm" aria-label="编辑持仓" @click="openEdit(position)"><Pencil class="h-3.5 w-3.5" /></Button><Button variant="danger-subtle" size="xsm" aria-label="删除持仓" @click="deletingPosition = position"><Trash2 class="h-3.5 w-3.5" /></Button></div></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="grid gap-3 md:hidden">
          <article v-for="position in equityPositions" :key="position.id" class="rounded-2xl border border-border/70 bg-card p-4">
            <div class="flex justify-between"><div><p class="font-semibold">{{ position.display_symbol }} · {{ position.name }}</p><p class="text-xs text-cyan">{{ position.asset_type }}</p></div><div class="flex gap-1"><button aria-label="编辑持仓" @click="openEdit(position)"><Pencil class="h-4 w-4" /></button><button aria-label="删除持仓" @click="deletingPosition = position"><Trash2 class="h-4 w-4 text-red-500" /></button></div></div>
            <dl class="mt-3 grid grid-cols-2 gap-2 text-sm"><div><dt class="text-xs text-secondary-text">数量</dt><dd>{{ formatDecimalText(position.quantity) }} 股</dd></div><div><dt class="text-xs text-secondary-text">最新价格</dt><dd>{{ amount(quotePrice(position)) }}</dd></div><div><dt class="text-xs text-secondary-text">市值</dt><dd>{{ amount(positionMarketValue(position)) }}</dd></div><div><dt class="text-xs text-secondary-text">未实现盈亏</dt><dd>{{ amount(positionPnl(position)) }}</dd></div></dl>
          </article>
        </div>
      </section>

      <section v-if="selectedAccountCode === 'US' && optionPositions.length" data-testid="option-section" class="space-y-3">
        <p class="rounded-xl border border-amber-500/25 bg-amber-500/10 p-3 text-xs text-amber-500">期权仅作手工持仓记录，不提供实时价格、市值或盈亏。</p>
        <div class="hidden overflow-hidden rounded-2xl border border-border/70 bg-card md:block">
          <table class="w-full text-sm"><thead class="bg-muted/40 text-left text-xs text-secondary-text"><tr><th class="p-3">标的</th><th>方向</th><th>Call/Put</th><th>行权价</th><th>到期日 / DTE</th><th>张数</th><th>平均成本</th><th>乘数</th><th>成本金额</th><th>状态</th><th>操作</th></tr></thead>
            <tbody class="divide-y divide-border/60"><tr v-for="position in optionPositions" :key="position.id"><td class="p-3">{{ position.option?.underlying_display_symbol }}</td><td>{{ position.position_side === 'LONG' ? '多头' : '空头' }}</td><td>{{ position.option?.option_type === 'CALL' ? 'Call' : 'Put' }}</td><td>{{ amount(position.option?.strike_price ?? null) }}</td><td>{{ position.option?.expiration_date }}<p :class="dteClass(position)" class="text-xs">{{ dteLabel(position) }}</p></td><td>{{ formatDecimalText(position.quantity.replace('-', '')) }} 张</td><td>{{ amount(position.avg_cost) }}</td><td>{{ formatDecimalText(position.contract_multiplier) }}</td><td>{{ amount(position.cost_amount) }}</td><td>{{ position.status }}</td><td><div class="flex gap-1"><Button v-if="position.option?.expiration_action_required" variant="ghost" size="xsm" @click="markStatus(position, 'CLOSED')">标记已平仓</Button><Button v-if="position.option?.expiration_action_required" variant="ghost" size="xsm" @click="markStatus(position, 'EXPIRED')">标记失效</Button><Button variant="ghost" size="xsm" aria-label="编辑期权" @click="openEdit(position)"><Pencil class="h-3.5 w-3.5" /></Button><Button variant="danger-subtle" size="xsm" aria-label="删除期权" @click="deletingPosition = position"><Trash2 class="h-3.5 w-3.5" /></Button></div></td></tr></tbody>
          </table>
        </div>
        <div class="grid gap-3 md:hidden"><article v-for="position in optionPositions" :key="position.id" class="rounded-2xl border border-border/70 bg-card p-4"><div class="flex justify-between"><div><p class="font-semibold">{{ position.option?.underlying_display_symbol }}</p><p class="text-xs text-amber-500">{{ position.position_side === 'LONG' ? '多头' : '空头' }} · {{ position.option?.option_type }}</p></div><div class="flex gap-2"><button aria-label="编辑期权" @click="openEdit(position)"><Pencil class="h-4 w-4" /></button><button aria-label="删除期权" @click="deletingPosition = position"><Trash2 class="h-4 w-4 text-red-500" /></button></div></div><dl class="mt-3 grid grid-cols-2 gap-2 text-sm"><div><dt class="text-xs text-secondary-text">行权价</dt><dd>{{ amount(position.option?.strike_price ?? null) }}</dd></div><div><dt class="text-xs text-secondary-text">到期日 / DTE</dt><dd>{{ position.option?.expiration_date }} · <span :class="dteClass(position)">{{ dteLabel(position) }}</span></dd></div><div><dt class="text-xs text-secondary-text">张数</dt><dd>{{ formatDecimalText(position.quantity.replace('-', '')) }}</dd></div><div><dt class="text-xs text-secondary-text">成本金额</dt><dd>{{ amount(position.cost_amount) }}</dd></div><div><dt class="text-xs text-secondary-text">状态</dt><dd>{{ position.status }}</dd></div></dl><div v-if="position.option?.expiration_action_required" class="mt-3 flex gap-2"><Button size="xsm" variant="secondary" @click="markStatus(position, 'CLOSED')">标记已平仓</Button><Button size="xsm" variant="danger-subtle" @click="markStatus(position, 'EXPIRED')">标记到期失效</Button></div></article></div>
      </section>
      <div v-if="!filteredPositions.length" class="rounded-2xl border border-dashed border-border p-10 text-center text-sm text-secondary-text">当前筛选下暂无持仓记录。</div>
    </template>

    <Dialog :is-open="dialogMode !== null" :title="dialogMode === 'edit' ? '编辑持仓' : dialogMode === 'option' ? '添加期权' : '添加股票 / ETF'" width="max-w-xl" @close="closeDialog">
      <form class="space-y-4" @submit.prevent="savePosition">
        <template v-if="dialogMode !== 'edit'">
          <label class="block text-sm font-medium">标的</label>
          <StockAutocomplete v-model="stockQuery" :placeholder="`搜索${selectedAccount?.name ?? ''}标的`" @submit="handleAutocomplete" />
          <p v-if="selectedCanonical" class="text-xs text-cyan">已选择 {{ selectedCanonical }} · {{ selectedUnderlyingType }}</p>
        </template>
        <template v-if="dialogMode === 'option'">
          <div class="grid grid-cols-2 gap-3"><label class="text-sm">Call / Put<select v-model="optionType" class="input-surface mt-1 w-full rounded-xl p-2"><option value="CALL">Call</option><option value="PUT">Put</option></select></label><Input v-model="expirationDate" label="到期日" type="date" /></div>
          <div class="grid grid-cols-2 gap-3"><Input v-model="strikePrice" label="行权价" inputmode="decimal" /><Input v-model="contractMultiplier" label="合约乘数" inputmode="decimal" /></div>
          <div class="grid grid-cols-2 gap-3"><Input v-model="optionContracts" label="张数" inputmode="numeric" /><label class="text-sm">持仓方向<select v-model="optionDirection" class="input-surface mt-1 w-full rounded-xl p-2"><option value="LONG">多头</option><option value="SHORT">空头</option></select></label></div>
        </template>
        <template v-else-if="dialogMode === 'edit' && editingPosition?.asset_type === 'OPTION'">
          <div class="grid grid-cols-2 gap-3"><Input v-model="optionContracts" label="张数" inputmode="numeric" /><label class="text-sm">持仓方向<select v-model="optionDirection" class="input-surface mt-1 w-full rounded-xl p-2"><option value="LONG">多头</option><option value="SHORT">空头</option></select></label></div>
        </template>
        <Input v-else v-model="quantity" label="数量" inputmode="decimal" />
        <Input v-model="avgCost" label="平均成本" inputmode="decimal" />
        <Input v-model="openedAt" label="建仓时间" type="datetime-local" />
        <label v-if="dialogMode === 'edit'" class="block text-sm">状态<select v-model="editStatus" class="input-surface mt-1 w-full rounded-xl p-2"><option value="OPEN">OPEN</option><option value="CLOSED">CLOSED</option><option v-if="editingPosition?.asset_type === 'OPTION'" value="EXPIRED">EXPIRED</option></select></label>
        <label class="block text-sm">备注<textarea v-model="notes" class="input-surface mt-1 min-h-20 w-full rounded-xl p-3" /></label>
        <p v-if="formError" class="text-sm text-red-500">{{ formError }}</p>
        <div class="flex justify-end gap-2"><Button variant="secondary" @click="closeDialog">取消</Button><Button type="submit" :is-loading="saving">保存</Button></div>
      </form>
    </Dialog>
    <ConfirmDialog :is-open="deletingPosition !== null" title="删除持仓记录" :message="`确认删除 ${deletingPosition?.display_symbol ?? ''}？此操作不可撤销。`" confirm-text="删除" is-danger @cancel="deletingPosition = null" @confirm="confirmDelete" />
  </div>
</template>
