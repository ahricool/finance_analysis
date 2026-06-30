<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { stockListApi, type MarketType, type StockHolding, type StockHoldingCreate } from '@/api/stockList';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Button from '@/components/common/Button.vue';
import Input from '@/components/common/Input.vue';
import RealtimeStatus from '@/components/stocks/RealtimeStatus.vue';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import StockAutocomplete from '@/components/StockAutocomplete/StockAutocomplete.vue';
import { useRealtimeQuotes } from '@/composables/useRealtimeQuotes';
import type { Market } from '@/types/stockIndex';
import {
  formatDecimalText,
  formatHoldingCostAmount,
  formatMarketCurrencyAmount,
  getMarketCurrencyCode,
  parseDecimalInput,
} from '@/utils/marketCurrency';
import { looksLikeStockCode } from '@/utils/validation';
import { ArrowDown, ArrowUp, ArrowUpDown, Briefcase, Pencil, Plus, Trash2, X } from 'lucide-vue-next';
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

type MarketFilter = MarketType | 'ALL';
type SortDirection = 'asc' | 'desc';
type StockListSortKey = 'code' | 'market_type' | 'name' | 'quantity' | 'avg_cost' | 'cost_amount';

type HoldingPrefill = {
  code: string;
  name?: string | null;
  marketType?: MarketType | null;
};

// ── State ─────────────────────────────────────────────────────────────────────
const items = ref<StockHolding[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const route = useRoute();
const router = useRouter();

// Dialog state
const showDialog = ref(false);
const editingId = ref<number | null>(null);
const formStockQuery = ref('');
const formCode = ref('');
const formName = ref('');
const formQuantity = ref('0');
const formAvgCost = ref('');
const formOpenedAt = ref('');
const formMarketType = ref<MarketType>('CN');
const formNotes = ref('');
const formError = ref<string | null>(null);
const saving = ref(false);

const showDeleteConfirm = ref(false);
const deletingId = ref<number | null>(null);
const deletingCode = ref('');
const detailItem = ref<StockHolding | null>(null);
const { status: realtimeStatus, getQuote } = useRealtimeQuotes();

const marketOptions: { value: MarketType; label: string }[] = [
  { value: 'CN', label: 'A股' },
  { value: 'US', label: '美股' },
  { value: 'HK', label: '港股' },
];
const marketFilterOptions: { value: MarketFilter; label: string }[] = [
  { value: 'ALL', label: '所有' },
  { value: 'US', label: '美股' },
  { value: 'HK', label: '港股' },
  { value: 'CN', label: 'A 股' },
];
const selectedMarket = ref<MarketFilter>('ALL');
const sortKey = ref<StockListSortKey | null>(null);
const sortDirection = ref<SortDirection>('asc');

const visibleItems = computed(() => {
  const filtered =
    selectedMarket.value === 'ALL'
      ? items.value
      : items.value.filter((item) => item.market_type === selectedMarket.value);

  const activeSortKey = sortKey.value;
  if (!activeSortKey) {
    return filtered;
  }

  const direction = sortDirection.value === 'asc' ? 1 : -1;
  return [...filtered].sort(
    (a, b) => compareSortValues(sortValue(a, activeSortKey), sortValue(b, activeSortKey)) * direction,
  );
});
const formCurrencyCode = computed(() => getMarketCurrencyCode(formMarketType.value));

function marketLabel(value: MarketType): string {
  return marketOptions.find((option) => option.value === value)?.label ?? 'A股';
}

function formatQuoteNumber(value: number | null | undefined, suffix = ''): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${value.toFixed(2)}${suffix}`;
}

function formatSignedQuoteNumber(value: number | null | undefined, suffix = ''): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}${suffix}`;
}

function movementClass(value: number | null | undefined): string {
  if (value && value > 0) return 'text-red-500';
  if (value && value < 0) return 'text-emerald-500';
  return 'text-secondary-text';
}

function sortValue(item: StockHolding, key: StockListSortKey): string | number | null | undefined {
  if (key === 'cost_amount') {
    return item.avg_cost ? Number(item.quantity) * Number(item.avg_cost) : null;
  }
  return item[key];
}

function normalizeSortValue(value: string | number | null | undefined): string | number {
  if (typeof value === 'number') return value;
  return String(value ?? '').trim().toLocaleLowerCase();
}

function compareSortValues(left: string | number | null | undefined, right: string | number | null | undefined): number {
  const normalizedLeft = normalizeSortValue(left);
  const normalizedRight = normalizeSortValue(right);
  if (typeof normalizedLeft === 'number' && typeof normalizedRight === 'number') {
    return normalizedLeft - normalizedRight;
  }
  return String(normalizedLeft).localeCompare(String(normalizedRight), 'zh-Hans-CN', {
    numeric: true,
    sensitivity: 'base',
  });
}

function toggleSort(key: StockListSortKey) {
  if (sortKey.value === key) {
    if (sortDirection.value === 'asc') {
      sortDirection.value = 'desc';
    } else {
      sortKey.value = null;
      sortDirection.value = 'asc';
    }
    return;
  }
  sortKey.value = key;
  sortDirection.value = 'asc';
}

function sortAria(key: StockListSortKey): 'none' | 'ascending' | 'descending' {
  if (sortKey.value !== key) return 'none';
  return sortDirection.value === 'asc' ? 'ascending' : 'descending';
}

function marketToMarketType(market?: Market): MarketType | null {
  if (market === 'CN' || market === 'US' || market === 'HK') {
    return market;
  }
  if (market === 'BSE') {
    return 'CN';
  }
  return null;
}

function formatStockQuery(code: string, name?: string | null): string {
  return name ? `${name}（${code}）` : code;
}

function toDatetimeLocalValue(value: string | null | undefined): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

function toIsoDatetime(value: string): string | null {
  const text = value.trim();
  if (!text) return null;
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function getQueryString(value: unknown): string {
  return Array.isArray(value) ? String(value[0] ?? '') : String(value ?? '');
}

watch(formStockQuery, (value) => {
  if (!formCode.value) return;
  const selectedQuery = formatStockQuery(formCode.value, formName.value);
  if (value !== selectedQuery && value !== formCode.value) {
    formCode.value = '';
    formName.value = '';
  }
});

// ── API Calls ─────────────────────────────────────────────────────────────────
async function loadList() {
  loading.value = true;
  error.value = null;
  try {
    const res = await stockListApi.list();
    items.value = res.items;
    total.value = res.total;
  } catch (e) {
    error.value = getParsedApiError(e);
  } finally {
    loading.value = false;
  }
}

async function save() {
  formError.value = null;
  const query = formStockQuery.value.trim();
  const code = (formCode.value.trim() || (looksLikeStockCode(query) ? query : '')).toUpperCase();
  if (!code) {
    formError.value = '请先搜索并选择股票';
    return;
  }
  const qty = parseDecimalInput(formQuantity.value);
  if (qty === null || qty < 0) {
    formError.value = '持仓数量必须为大于等于 0 的数字';
    return;
  }
  const avgCostText = formAvgCost.value.trim();
  const avgCost = avgCostText ? parseDecimalInput(avgCostText) : null;
  if (avgCostText && (avgCost === null || avgCost < 0)) {
    formError.value = '平均持仓成本必须为大于等于 0 的数字';
    return;
  }
  const openedAt = toIsoDatetime(formOpenedAt.value);
  if (formOpenedAt.value.trim() && openedAt === null) {
    formError.value = '首次建仓时间格式不正确';
    return;
  }
  saving.value = true;
  try {
    if (editingId.value !== null) {
      const updated = await stockListApi.update(editingId.value, {
        name: formName.value.trim() || undefined,
        quantity: formQuantity.value.trim(),
        avg_cost: avgCostText || null,
        opened_at: openedAt,
        notes: formNotes.value.trim(),
      });
      const idx = items.value.findIndex((i) => i.id === editingId.value);
      if (idx !== -1) items.value[idx] = updated;
    } else {
      const body: StockHoldingCreate = {
        code,
        name: formName.value.trim() || undefined,
        quantity: formQuantity.value.trim(),
        avg_cost: avgCostText || null,
        opened_at: openedAt,
        market_type: formMarketType.value,
        notes: formNotes.value.trim() || undefined,
      };
      const created = await stockListApi.create(body);
      items.value.push(created);
      total.value++;
    }
    closeDialog();
  } catch (e) {
    const parsed = getParsedApiError(e);
    formError.value = parsed.message || '操作失败，请重试';
  } finally {
    saving.value = false;
  }
}

async function confirmDelete() {
  if (deletingId.value === null) return;
  try {
    await stockListApi.remove(deletingId.value);
    items.value = items.value.filter((i) => i.id !== deletingId.value);
    total.value--;
  } catch (e) {
    error.value = getParsedApiError(e);
  } finally {
    showDeleteConfirm.value = false;
    deletingId.value = null;
    deletingCode.value = '';
  }
}

// ── Dialog helpers ────────────────────────────────────────────────────────────
function openCreate(prefill?: HoldingPrefill) {
  editingId.value = null;
  formCode.value = prefill?.code ?? '';
  formName.value = prefill?.name ?? '';
  formStockQuery.value = prefill?.code ? formatStockQuery(prefill.code, prefill.name) : '';
  formQuantity.value = '0';
  formAvgCost.value = '';
  formOpenedAt.value = '';
  formMarketType.value = prefill?.marketType ?? 'CN';
  formNotes.value = '';
  formError.value = null;
  showDialog.value = true;
}

function openEdit(item: StockHolding) {
  editingId.value = item.id;
  formCode.value = item.code;
  formName.value = item.name ?? '';
  formStockQuery.value = formatStockQuery(item.code, item.name);
  formQuantity.value = String(item.quantity);
  formAvgCost.value = item.avg_cost ?? '';
  formOpenedAt.value = toDatetimeLocalValue(item.opened_at);
  formMarketType.value = item.market_type;
  formNotes.value = item.notes ?? '';
  formError.value = null;
  showDialog.value = true;
}

function closeDialog() {
  showDialog.value = false;
  editingId.value = null;
}

function handleStockAutocompleteSubmit(
  code: string,
  name?: string,
  _source?: 'manual' | 'autocomplete',
  market?: Market,
) {
  formCode.value = code;
  formName.value = name ?? '';
  formStockQuery.value = formatStockQuery(code, name);
  formMarketType.value = marketToMarketType(market) ?? formMarketType.value;
}

function openDelete(item: StockHolding) {
  deletingId.value = item.id;
  deletingCode.value = item.code;
  showDeleteConfirm.value = true;
}

function maybeOpenCreateFromRoute() {
  const code = getQueryString(route.query.code).trim().toUpperCase();
  if (!code) return;
  const marketType = marketToMarketType(getQueryString(route.query.market_type) as Market) ?? 'CN';
  const exists = items.value.some((item) => item.code.toUpperCase() === code && item.market_type === marketType);
  if (exists) {
    error.value = {
      title: '该股票已经建仓',
      message: `${code} 已在持仓股中，请编辑现有持仓。`,
      rawMessage: `${code} 已在持仓股中，请编辑现有持仓。`,
      category: 'http_error',
      status: 409,
    };
    void router.replace({ name: 'stock-list' });
    return;
  }
  openCreate({
    code,
    name: getQueryString(route.query.name).trim() || null,
    marketType,
  });
  void router.replace({ name: 'stock-list' });
}

onMounted(async () => {
  await loadList();
  maybeOpenCreateFromRoute();
});
</script>

<template>
  <div class="mx-auto w-full px-4 py-6 sm:px-6">
    <!-- Header -->
    <div class="mb-6 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary-gradient text-[hsl(var(--primary-foreground))] shadow-soft-card">
          <Briefcase class="h-5 w-5" />
        </div>
        <div>
          <h1 class="text-lg font-semibold text-foreground">持仓股</h1>
          <p class="text-xs text-secondary-text">持仓 {{ total }} 只</p>
        </div>
      </div>
      <Button variant="primary" size="sm" @click="openCreate">
        <Plus class="mr-1.5 h-4 w-4" />
        添加
      </Button>
    </div>

    <!-- Error -->
    <ApiErrorAlert v-if="error" :error="error" class="mb-4" />

    <!-- Loading skeleton -->
    <div v-if="loading" class="space-y-2">
      <div v-for="n in 4" :key="n" class="h-14 animate-pulse rounded-xl bg-card" />
    </div>

    <!-- Empty state -->
    <div
      v-else-if="!items.length"
      class="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-border/60 py-16 text-center"
    >
      <Briefcase class="h-10 w-10 text-secondary-text/40" />
      <p class="text-sm text-secondary-text">暂无持仓股，点击「添加」开始记录</p>
      <p class="text-xs text-secondary-text/60">持仓股列表同时作为每日分析的目标股票</p>
    </div>

    <template v-else>
      <div class="mb-3 rounded-2xl border border-border/70 bg-card/94 p-4 shadow-soft-card">
        <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <label class="block text-sm font-medium text-foreground">
            <span class="mb-1 block text-xs text-muted-text">市场</span>
            <select
              v-model="selectedMarket"
              class="h-9 w-full min-w-[180px] rounded-xl border border-border/70 bg-background px-3 text-sm text-foreground outline-none transition-colors focus:border-primary"
            >
              <option v-for="option in marketFilterOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </label>
          <div class="flex items-center gap-3">
            <RealtimeStatus :status="realtimeStatus" />
            <p class="whitespace-nowrap text-xs text-muted-text">显示 {{ visibleItems.length }} / {{ total }} 只</p>
          </div>
        </div>
      </div>

      <!-- Table -->
      <div class="overflow-x-auto rounded-2xl border border-border/70 bg-card/94 shadow-soft-card">
        <table class="w-full min-w-[1220px] table-fixed text-left text-sm">
          <colgroup>
            <col class="w-[120px]" />
            <col class="w-[160px]" />
            <col class="w-[90px]" />
            <col class="w-[115px]" />
            <col class="w-[120px]" />
            <col class="w-[110px]" />
            <col class="w-[130px]" />
            <col class="w-[130px]" />
            <col class="w-[145px]" />
            <col class="w-[100px]" />
          </colgroup>
          <thead class="border-b border-border/70 text-xs text-muted-text">
            <tr>
              <th class="whitespace-nowrap px-4 py-3 font-medium" :aria-sort="sortAria('code')">
                <button class="flex items-center gap-1.5 transition-colors hover:text-foreground" @click="toggleSort('code')">
                  代码
                  <ArrowUp v-if="sortKey === 'code' && sortDirection === 'asc'" class="h-3.5 w-3.5" />
                  <ArrowDown v-else-if="sortKey === 'code'" class="h-3.5 w-3.5" />
                  <ArrowUpDown v-else class="h-3.5 w-3.5 opacity-50" />
                </button>
              </th>
              <th class="whitespace-nowrap px-4 py-3 font-medium" :aria-sort="sortAria('name')">
                <button class="flex items-center gap-1.5 transition-colors hover:text-foreground" @click="toggleSort('name')">
                  名称
                  <ArrowUp v-if="sortKey === 'name' && sortDirection === 'asc'" class="h-3.5 w-3.5" />
                  <ArrowDown v-else-if="sortKey === 'name'" class="h-3.5 w-3.5" />
                  <ArrowUpDown v-else class="h-3.5 w-3.5 opacity-50" />
                </button>
              </th>
              <th class="whitespace-nowrap px-4 py-3 font-medium" :aria-sort="sortAria('market_type')">
                <button class="flex items-center gap-1.5 transition-colors hover:text-foreground" @click="toggleSort('market_type')">
                  市场
                  <ArrowUp v-if="sortKey === 'market_type' && sortDirection === 'asc'" class="h-3.5 w-3.5" />
                  <ArrowDown v-else-if="sortKey === 'market_type'" class="h-3.5 w-3.5" />
                  <ArrowUpDown v-else class="h-3.5 w-3.5 opacity-50" />
                </button>
              </th>
              <th class="whitespace-nowrap px-4 py-3 text-right font-medium">最新价</th>
              <th class="whitespace-nowrap px-4 py-3 text-right font-medium">今日涨跌额</th>
              <th class="whitespace-nowrap px-4 py-3 text-right font-medium">今日涨跌幅</th>
              <th class="whitespace-nowrap px-4 py-3 text-right font-medium" :aria-sort="sortAria('quantity')">
                <button
                  class="ml-auto flex items-center gap-1.5 transition-colors hover:text-foreground"
                  @click="toggleSort('quantity')"
                >
                  持仓数量
                  <ArrowUp v-if="sortKey === 'quantity' && sortDirection === 'asc'" class="h-3.5 w-3.5" />
                  <ArrowDown v-else-if="sortKey === 'quantity'" class="h-3.5 w-3.5" />
                  <ArrowUpDown v-else class="h-3.5 w-3.5 opacity-50" />
                </button>
              </th>
              <th class="whitespace-nowrap px-4 py-3 text-right font-medium" :aria-sort="sortAria('avg_cost')">
                <button
                  class="ml-auto flex items-center gap-1.5 transition-colors hover:text-foreground"
                  @click="toggleSort('avg_cost')"
                >
                  平均成本
                  <ArrowUp v-if="sortKey === 'avg_cost' && sortDirection === 'asc'" class="h-3.5 w-3.5" />
                  <ArrowDown v-else-if="sortKey === 'avg_cost'" class="h-3.5 w-3.5" />
                  <ArrowUpDown v-else class="h-3.5 w-3.5 opacity-50" />
                </button>
              </th>
              <th class="whitespace-nowrap px-4 py-3 text-right font-medium" :aria-sort="sortAria('cost_amount')">
                <button
                  class="ml-auto flex items-center gap-1.5 transition-colors hover:text-foreground"
                  @click="toggleSort('cost_amount')"
                >
                  持仓成本金额
                  <ArrowUp v-if="sortKey === 'cost_amount' && sortDirection === 'asc'" class="h-3.5 w-3.5" />
                  <ArrowDown v-else-if="sortKey === 'cost_amount'" class="h-3.5 w-3.5" />
                  <ArrowUpDown v-else class="h-3.5 w-3.5 opacity-50" />
                </button>
              </th>
              <th class="whitespace-nowrap px-4 py-3 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!visibleItems.length">
              <td colspan="10" class="px-4 py-10 text-center text-muted-text">当前筛选下暂无持仓股</td>
            </tr>
            <template v-else>
              <tr
                v-for="item in visibleItems"
                :key="item.id"
                class="border-b border-border/50 transition-colors last:border-0 hover:bg-hover/70"
              >
                <td class="px-4 py-3">
                  <button class="font-mono text-sm font-semibold text-primary hover:underline" @click="detailItem = item">
                    {{ item.code }}
                  </button>
                </td>
                <td class="truncate px-4 py-3 font-medium text-foreground">
                  <button class="max-w-full truncate text-left hover:text-primary hover:underline" @click="detailItem = item">{{ item.name || '—' }}</button>
                </td>
                <td class="px-4 py-3">
                  <span class="rounded-lg border border-border/60 bg-background px-2 py-0.5 text-xs font-medium text-secondary-text">
                    {{ marketLabel(item.market_type) }}
                  </span>
                </td>
                <td class="whitespace-nowrap px-4 py-3 text-right font-medium tabular-nums text-foreground">
                  {{ formatQuoteNumber(getQuote(item.code, item.market_type)?.last_price) }}
                </td>
                <td class="whitespace-nowrap px-4 py-3 text-right font-medium tabular-nums" :class="movementClass(getQuote(item.code, item.market_type)?.change_amount)">
                  {{ formatSignedQuoteNumber(getQuote(item.code, item.market_type)?.change_amount) }}
                </td>
                <td class="whitespace-nowrap px-4 py-3 text-right font-medium tabular-nums" :class="movementClass(getQuote(item.code, item.market_type)?.change_pct)">
                  {{ formatSignedQuoteNumber(getQuote(item.code, item.market_type)?.change_pct, '%') }}
                </td>
                <td class="whitespace-nowrap px-4 py-3 text-right font-semibold tabular-nums text-foreground">
                  {{ formatDecimalText(item.quantity) }} 股
                </td>
                <td class="whitespace-nowrap px-4 py-3 text-right tabular-nums text-secondary-text">
                  {{ formatMarketCurrencyAmount(item.avg_cost, item.market_type) }}
                </td>
                <td class="whitespace-nowrap px-4 py-3 text-right font-medium tabular-nums text-foreground">
                  {{ formatHoldingCostAmount(item.quantity, item.avg_cost, item.market_type) }}
                </td>
                <td class="px-4 py-3 text-right">
                  <div class="flex justify-end gap-1">
                    <button
                      class="rounded-lg p-1.5 text-secondary-text hover:bg-hover hover:text-foreground"
                      aria-label="编辑"
                      @click="openEdit(item)"
                    >
                      <Pencil class="h-4 w-4" />
                    </button>
                    <button
                      class="rounded-lg p-1.5 text-secondary-text hover:bg-destructive/10 hover:text-destructive"
                      aria-label="删除"
                      @click="openDelete(item)"
                    >
                      <Trash2 class="h-4 w-4" />
                    </button>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </template>

    <StockDetailDialog
      :stock="detailItem"
      :quote="detailItem ? getQuote(detailItem.code, detailItem.market_type) : undefined"
      kind="holding"
      @close="detailItem = null"
    />

    <!-- Add / Edit Dialog -->
    <Teleport to="body">
      <div
        v-if="showDialog"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
        @click.self="closeDialog"
      >
        <div class="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl">
          <div class="mb-5 flex items-center justify-between">
            <h2 class="text-base font-semibold text-foreground">
              {{ editingId !== null ? '编辑持仓股' : '添加持仓股' }}
            </h2>
            <button class="rounded-lg p-1 text-secondary-text hover:text-foreground" @click="closeDialog">
              <X class="h-5 w-5" />
            </button>
          </div>

          <div class="space-y-4">
            <div>
              <label class="mb-1 block text-sm font-medium text-foreground">股票 *</label>
              <StockAutocomplete
                v-model="formStockQuery"
                placeholder="搜索股票代码、名称或拼音"
                :disabled="editingId !== null"
                @submit="handleStockAutocompleteSubmit"
              />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-foreground">市场</label>
              <select
                v-model="formMarketType"
                class="h-10 w-full rounded-xl border border-border bg-background px-3 text-sm text-foreground outline-none transition-colors focus:border-primary disabled:cursor-not-allowed disabled:opacity-70"
                :disabled="editingId !== null"
              >
                <option v-for="option in marketOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-foreground">币种</label>
              <div class="flex h-10 items-center rounded-xl border border-border bg-background px-3 text-sm font-medium text-secondary-text">
                {{ formCurrencyCode }}
              </div>
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-foreground">持仓数量（股）</label>
              <Input v-model="formQuantity" type="number" min="0" step="0.000001" placeholder="0" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-foreground">平均持仓成本</label>
              <Input v-model="formAvgCost" type="number" min="0" step="0.000001" placeholder="可不填" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-foreground">首次建仓时间</label>
              <Input v-model="formOpenedAt" type="datetime-local" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-foreground">备注（可选）</label>
              <Input v-model="formNotes" placeholder="备注信息" />
            </div>
            <p v-if="formError" class="text-sm text-destructive">{{ formError }}</p>
          </div>

          <div class="mt-6 flex justify-end gap-3">
            <Button variant="ghost" @click="closeDialog">取消</Button>
            <Button variant="primary" :disabled="saving" @click="save">
              {{ saving ? '保存中…' : '保存' }}
            </Button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Delete Confirm Dialog -->
    <Teleport to="body">
      <div
        v-if="showDeleteConfirm"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
        @click.self="showDeleteConfirm = false"
      >
        <div class="w-full max-w-sm rounded-2xl border border-border bg-card p-6 shadow-2xl">
          <h2 class="mb-2 text-base font-semibold text-foreground">删除持仓股</h2>
          <p class="mb-5 text-sm text-secondary-text">
            确认从持仓股中移除
            <span class="font-mono font-semibold text-foreground">{{ deletingCode }}</span>？
          </p>
          <div class="flex justify-end gap-3">
            <Button variant="ghost" @click="showDeleteConfirm = false">取消</Button>
            <Button variant="danger" @click="confirmDelete">确认删除</Button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
