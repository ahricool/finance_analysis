<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import type { RealtimePatternState, RealtimeTrend } from '@/api/realtimeMarket';
import {
  watchListApi,
  type MarketType,
  type WatchListItem,
  type WatchListItemCreate,
  type WatchListTag,
  type WatchListTagDraft,
} from '@/api/watchList';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import AppConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import WatchListTagPicker from '@/components/watch-list/WatchListTagPicker.vue';
import WatchListTagManager from '@/components/watch-list/WatchListTagManager.vue';
import IntradayStockPanel from '@/components/stocks/IntradayStockPanel.vue';
import PatternStatus from '@/components/stocks/PatternStatus.vue';
import RealtimeStatus from '@/components/stocks/RealtimeStatus.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import TrendStatus from '@/components/stocks/TrendStatus.vue';
import IntradayDirectionStatus from '@/components/stocks/IntradayDirectionStatus.vue';
import StockAutocomplete from '@/components/StockAutocomplete/StockAutocomplete.vue';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { useCurrentTime } from '@/composables/useCurrentTime';
import { useRealtimeQuotes } from '@/composables/useRealtimeQuotes';
import type { Market } from '@/types/stockIndex';
import { formatSecurityLabel } from '@/utils/security';
import { signedTextClass } from '@/utils/marketTone';
import { calculateIntradayDirection, intradayDirectionSortValue } from '@/utils/intradayDirection';
import { Eye, Heart, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-vue-next';
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';

type TagFilter = 'ALL' | 'UNGROUPED' | number;
type SortDirection = 'asc' | 'desc';
type WatchListSortKey =
  | 'is_favorite'
  | 'code'
  | 'market_type'
  | 'name'
  | 'last_price'
  | 'change_amount'
  | 'change_pct'
  | 'trend'
  | 'pattern'
  | 'intraday_direction';

// ── State ─────────────────────────────────────────────────────────────────────
const items = ref<WatchListItem[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);

// Dialog state
const showDialog = ref(false);
const editingId = ref<number | null>(null);
const formStockQuery = ref('');
const formCode = ref('');
const formName = ref('');
const formNotes = ref('');
const formMarketType = ref<MarketType | null>(null);
const formError = ref<string | null>(null);
const saving = ref(false);

const showDeleteConfirm = ref(false);
const deletingId = ref<number | null>(null);
const deletingCode = ref('');
const togglingFavoriteId = ref<number | null>(null);
const detailItem = ref<WatchListItem | null>(null);
const expandedCode = ref<string | null>(null);
const selectedMarket = ref<'CN' | 'US'>('CN');
const selectedTag = ref<TagFilter>('ALL');
const tags = ref<WatchListTag[]>([]);
const formTags = ref<WatchListTagDraft[]>([]);
const showTagManager = ref(false);
watch(selectedMarket, () => { expandedCode.value = null; });
watch(selectedTag, () => { expandedCode.value = null; });
const filters = computed(() => ({
  market: selectedMarket.value,
  tagId: typeof selectedTag.value === 'number' ? selectedTag.value : undefined,
  ungrouped: selectedTag.value === 'UNGROUPED',
}));
const { status: realtimeStatus, getQuote } = useRealtimeQuotes(() => ({ scope: 'watch-list', ...filters.value }));
const currentTime = useCurrentTime();

const marketOptions: { value: MarketType; label: string }[] = [
  { value: 'CN', label: 'A股' },
  { value: 'US', label: '美股' },
  { value: 'HK', label: '港股' },
];
const sortKey = ref<WatchListSortKey | null>('is_favorite');
const sortDirection = ref<SortDirection>('desc');

const visibleItems = computed(() => {
  const filtered = items.value;

  const activeSortKey = sortKey.value;
  if (!activeSortKey) {
    return filtered;
  }

  const direction = sortDirection.value === 'asc' ? 1 : -1;
  return [...filtered].sort(
    (a, b) => {
      const left = sortValue(a, activeSortKey);
      const right = sortValue(b, activeSortKey);
      if (left == null) return right == null ? a.id - b.id : 1;
      if (right == null) return -1;
      return compareSortValues(left, right) * direction;
    },
  );
});

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
  return signedTextClass(value);
}

function sortValue(
  item: WatchListItem,
  key: WatchListSortKey,
): string | number | boolean | null | undefined {
  const quote = getQuote(item.code, item.market_type);
  if (key === 'last_price') return quote?.last_price;
  if (key === 'change_amount') return quote?.change_amount;
  if (key === 'change_pct') return quote?.change_pct;
  if (key === 'trend') return trendSortValue(quote?.trend_1m);
  if (key === 'pattern') return patternSortValue(quote?.pattern_1m);
  if (key === 'intraday_direction') {
    return intradayDirectionSortValue(
      calculateIntradayDirection(quote, item.market_type, currentTime.value),
    );
  }
  return item[key];
}

function trendSortValue(trend: RealtimeTrend | null | undefined): number | null {
  if (!trend || trend.state === 'insufficient' || trend.streak <= 0) return null;
  if (trend.state === 'above') return trend.streak;
  if (trend.state === 'below') return -trend.streak;
  return 0;
}

function patternSortValue(pattern: RealtimePatternState | null | undefined): number | null {
  const signal = pattern?.status === 'active' ? pattern.signal : null;
  if (!signal) return null;
  const stage = { forming: 1, warning: 2, confirmed: 3 }[signal.stage];
  const direction = ['bullish_continuation', 'bearish_to_bullish', 'bullish_breakout'].includes(
    signal.direction,
  )
    ? 1
    : ['bearish_continuation', 'bullish_to_bearish', 'bearish_breakout'].includes(signal.direction)
      ? -1
      : 0;
  return stage * 1000 + signal.quality_score * 10 + direction;
}

function normalizeSortValue(value: string | number | boolean | null | undefined): string | number {
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (typeof value === 'number') return value;
  return String(value ?? '')
    .trim()
    .toLocaleLowerCase();
}

function compareSortValues(
  left: string | number | boolean | null | undefined,
  right: string | number | boolean | null | undefined,
): number {
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

function toggleSort(key: WatchListSortKey) {
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
  return formatSecurityLabel(code, name);
}

watch(formStockQuery, (value) => {
  if (!formCode.value) return;
  const selectedQuery = formatStockQuery(formCode.value, formName.value);
  if (value !== selectedQuery && value !== formCode.value) {
    formCode.value = '';
    formName.value = '';
    formMarketType.value = null;
  }
});

let listGeneration = 0;
let listController: AbortController | null = null;
onUnmounted(() => { ++listGeneration; listController?.abort(); });
watch(filters, () => { void loadList(); });

function mergeTags(values: WatchListTag[]) {
  const merged = new Map(tags.value.map(tag => [tag.id, tag]));
  values.forEach(tag => merged.set(tag.id, tag));
  tags.value = [...merged.values()].sort((a, b) => a.id - b.id);
}
function renameTag(tag: WatchListTag) {
  mergeTags([tag]);
  items.value.forEach(item => { item.tags = item.tags.map(value => value.id === tag.id ? tag : value); });
  if (detailItem.value) detailItem.value.tags = detailItem.value.tags.map(value => value.id === tag.id ? tag : value);
}
function deleteTag(id: number) {
  tags.value = tags.value.filter(tag => tag.id !== id);
  if (selectedTag.value === id) selectedTag.value = 'ALL';
  else void loadList();
}

// ── API Calls ─────────────────────────────────────────────────────────────────
async function loadList() {
  const generation = ++listGeneration;
  listController?.abort();
  listController = new AbortController();
  loading.value = true;
  error.value = null;
  items.value = [];
  total.value = 0;
  try {
    const res = await watchListApi.list(filters.value, listController.signal);
    if (generation !== listGeneration) return;
    items.value = res.items;
    total.value = res.total;
  } catch (e) {
    if (generation === listGeneration) error.value = getParsedApiError(e);
  } finally {
    if (generation === listGeneration) loading.value = false;
  }
}

async function save() {
  if (saving.value) return;
  formError.value = null;
  const code = formCode.value.trim();
  if (editingId.value === null && (!code || formMarketType.value !== selectedMarket.value)) {
    formError.value = '请先搜索并选择股票';
    return;
  }
  saving.value = true;
  const savedTags = formTags.value.map(tag => tag.id !== undefined ? { id: tag.id } : { name: tag.name });
  try {
    if (editingId.value !== null) {
      const updated = await watchListApi.update(editingId.value, {
        notes: formNotes.value.trim(),
        tags: savedTags,
      });
      mergeTags(updated.tags);
    } else {
      const body: WatchListItemCreate = {
        code,
        name: formName.value.trim() || undefined,
        notes: formNotes.value.trim() || undefined,
        market_type: selectedMarket.value,
        tags: savedTags,
      };
      const created = await watchListApi.create(body);
      mergeTags(created.tags);
    }
    closeDialog();
    await loadList();
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
    await watchListApi.remove(deletingId.value);
    await loadList();
  } catch (e) {
    error.value = getParsedApiError(e);
  } finally {
    showDeleteConfirm.value = false;
    deletingId.value = null;
    deletingCode.value = '';
  }
}

// ── Dialog helpers ────────────────────────────────────────────────────────────
function openCreate() {
  editingId.value = null;
  formStockQuery.value = '';
  formCode.value = '';
  formName.value = '';
  formNotes.value = '';
  formTags.value = [];
  formMarketType.value = null;
  formError.value = null;
  showDialog.value = true;
}

function openEdit(item: WatchListItem) {
  editingId.value = item.id;
  formCode.value = item.code;
  formName.value = item.name ?? '';
  formStockQuery.value = formatStockQuery(item.code, item.name);
  formNotes.value = item.notes ?? '';
  formTags.value = item.tags.map(tag => ({ ...tag }));
  formMarketType.value = item.market_type;
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
  source?: 'manual' | 'autocomplete',
  market?: Market,
) {
  const marketType = marketToMarketType(market);
  if (source !== 'autocomplete' || marketType !== selectedMarket.value) {
    formCode.value = '';
    formName.value = '';
    formMarketType.value = null;
    formError.value = '请先搜索并选择股票';
    return;
  }
  formCode.value = code;
  formName.value = name ?? '';
  formStockQuery.value = formatStockQuery(code, name);
  formMarketType.value = marketType;
  formError.value = null;
}

function openDelete(item: WatchListItem) {
  deletingId.value = item.id;
  deletingCode.value = item.code;
  showDeleteConfirm.value = true;
}

async function toggleFavorite(item: WatchListItem) {
  if (togglingFavoriteId.value !== null) return;
  togglingFavoriteId.value = item.id;
  const next = !item.is_favorite;
  try {
    const updated = await watchListApi.update(item.id, { is_favorite: next });
    const idx = items.value.findIndex((i) => i.id === item.id);
    if (idx !== -1) items.value[idx] = updated;
    items.value.sort((a, b) => {
      if (a.is_favorite !== b.is_favorite) return a.is_favorite ? -1 : 1;
      return a.created_at.localeCompare(b.created_at);
    });
  } catch (e) {
    error.value = getParsedApiError(e);
  } finally {
    togglingFavoriteId.value = null;
  }
}

onMounted(() => {
  void loadList();
  void watchListApi.listTags().then(mergeTags).catch(e => { error.value = getParsedApiError(e); });
});
</script>

<template>
  <div class="w-full">
    <!-- Header -->
    <div class="mb-6 flex items-center justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold tracking-tight text-foreground">
          自选股
        </h2>
        <p class="mt-1 text-sm text-muted-foreground">
          跟踪关注标的的实时行情，查看价格走势与股票详情。
        </p>
      </div>
      <Button
        variant="default"
        size="sm"
        @click="openCreate"
      >
        <Plus />
        添加
      </Button>
    </div>

    <!-- Error -->
    <ApiErrorAlert
      v-if="error"
      :error="error"
      class="mb-4"
    />

    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div
        role="group"
        aria-label="自选股市场"
        class="inline-flex items-center gap-1 rounded-lg bg-muted/80 p-1 ring-1 ring-border/50"
      >
        <Button
          v-for="market in (['US', 'CN'] as const)"
          :key="market"
          variant="ghost"
          size="sm"
          :class="selectedMarket === market ? 'bg-background text-foreground shadow-sm hover:bg-background' : 'text-muted-foreground'"
          :aria-pressed="selectedMarket === market"
          :data-testid="`market-${market.toLowerCase()}`"
          @click="selectedMarket = market"
        >
          {{ market === 'US' ? '美股' : 'A股' }}
        </Button>
      </div>
      <div class="flex items-center gap-3">
        <RealtimeStatus :status="realtimeStatus" />
        <p
          class="whitespace-nowrap text-xs text-muted-foreground"
          data-testid="watch-list-count"
        >
          显示 {{ visibleItems.length }} / {{ total }} 只
        </p>
      </div>
    </div>
    <div
      class="mb-4 flex flex-wrap items-center gap-2"
      role="group"
      aria-label="分组筛选"
      data-testid="tag-filters"
    >
      <Button
        variant="outline"
        size="sm"
        :class="selectedTag === 'ALL' && 'bg-muted'"
        :aria-pressed="selectedTag === 'ALL'"
        @click="selectedTag = 'ALL'"
      >
        全部
      </Button>
      <Button
        variant="outline"
        size="sm"
        :class="selectedTag === 'UNGROUPED' && 'bg-muted'"
        :aria-pressed="selectedTag === 'UNGROUPED'"
        @click="selectedTag = 'UNGROUPED'"
      >
        未分组
      </Button>
      <Button
        v-for="tag in tags"
        :key="tag.id"
        variant="outline"
        size="sm"
        class="h-auto max-w-full whitespace-normal py-1.5"
        :class="selectedTag === tag.id && 'bg-muted'"
        :aria-pressed="selectedTag === tag.id"
        @click="selectedTag = tag.id"
      >
        <span class="break-all">{{ tag.name }}</span>
      </Button>
      <Button
        variant="ghost"
        size="sm"
        class="text-muted-foreground"
        @click="showTagManager = true"
      >
        管理标签
      </Button>
    </div>

    <div
      v-if="loading"
      class="space-y-2"
    >
      <Skeleton
        v-for="n in 5"
        :key="n"
        class="h-16 w-full"
      />
    </div>
    <Empty v-else-if="!visibleItems.length">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Eye />
        </EmptyMedia>
        <EmptyTitle>{{ total === 0 ? '当前市场暂无自选股' : '当前分组暂无自选股' }}</EmptyTitle>
        <EmptyDescription>{{ total === 0 ? '点击「添加」开始关注股票并跟踪实时行情。' : '可切换分组，或添加股票到此分组。' }}</EmptyDescription>
      </EmptyHeader>
      <Button @click="openCreate">
        <Plus />添加自选股
      </Button>
    </Empty>
    <template v-else>
      <Card class="block">
        <CardHeader><CardTitle>自选股列表</CardTitle><CardDescription>点击股票名称查看详情，点击行展开分钟行情；次要操作收纳在行菜单中。</CardDescription></CardHeader><CardContent>
          <Table class="w-full min-w-[1500px] table-auto text-left text-sm">
            <colgroup>
              <col class="w-[110px]" />
              <col class="w-[260px]" />
              <col class="w-[110px]" />
              <col class="w-[120px]" />
              <col class="w-[150px]" />
              <col class="w-[150px]" />
              <col class="w-[140px]" />
              <col class="w-[210px]" />
              <col class="w-[140px]" />
              <col class="w-[152px]" />
            </colgroup>
            <TableHeader class="border-b border-border/70 text-xs text-muted-foreground">
              <TableRow>
                <SortableTableHeader
                  scope="watch"
                  label="关注"
                  :active="sortKey === 'is_favorite'"
                  :direction="sortDirection"
                  @sort="toggleSort('is_favorite')"
                />
                <SortableTableHeader
                  scope="watch"
                  label="股票"
                  :active="sortKey === 'code'"
                  :direction="sortDirection"
                  @sort="toggleSort('code')"
                />
                <SortableTableHeader
                  scope="watch"
                  label="市场"
                  :active="sortKey === 'market_type'"
                  :direction="sortDirection"
                  @sort="toggleSort('market_type')"
                />
                <SortableTableHeader
                  scope="watch"
                  label="最新价"
                  align="right"
                  :active="sortKey === 'last_price'"
                  :direction="sortDirection"
                  @sort="toggleSort('last_price')"
                />
                <SortableTableHeader
                  scope="watch"
                  label="今日涨跌额"
                  align="right"
                  :active="sortKey === 'change_amount'"
                  :direction="sortDirection"
                  @sort="toggleSort('change_amount')"
                />
                <SortableTableHeader
                  scope="watch"
                  label="今日涨跌幅"
                  align="right"
                  :active="sortKey === 'change_pct'"
                  :direction="sortDirection"
                  @sort="toggleSort('change_pct')"
                />
                <SortableTableHeader
                  scope="watch"
                  label="趋势持续"
                  :active="sortKey === 'trend'"
                  :direction="sortDirection"
                  @sort="toggleSort('trend')"
                />
                <SortableTableHeader
                  scope="watch"
                  label="最近形态"
                  :active="sortKey === 'pattern'"
                  :direction="sortDirection"
                  @sort="toggleSort('pattern')"
                />
                <SortableTableHeader
                  scope="watch"
                  label="日内方向状态"
                  :active="sortKey === 'intraday_direction'"
                  :direction="sortDirection"
                  @sort="toggleSort('intraday_direction')"
                />
                <TableHead class="whitespace-nowrap px-4 py-3 text-right font-medium">
                  操作
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-if="!visibleItems.length">
                <TableCell
                  colspan="10"
                  class="px-4 py-10 text-center text-muted-foreground"
                >
                  当前筛选下暂无自选股
                </TableCell>
              </TableRow>
              <template v-else>
                <template
                  v-for="item in visibleItems"
                  :key="item.id"
                >
                  <TableRow
                    class="cursor-pointer border-b border-border/50 transition-colors last:border-0 hover:bg-muted/70 focus-visible:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                    tabindex="0"
                    :aria-label="`展开 ${formatSecurityLabel(item.code, item.name)} 分钟行情`"
                    :aria-expanded="expandedCode === item.code"
                    @click="expandedCode = expandedCode === item.code ? null : item.code"
                    @keydown.enter.self="expandedCode = expandedCode === item.code ? null : item.code"
                    @keydown.space.self.prevent="expandedCode = expandedCode === item.code ? null : item.code"
                  >
                    <TableCell class="px-4 py-3">
                      <button
                        type="button"
                        class="rounded-lg p-1.5 transition-colors disabled:opacity-50"
                        :class="
                          item.is_favorite
                            ? 'text-brand hover:text-brand/90'
                            : 'text-muted-foreground hover:text-brand'
                        "
                        :disabled="togglingFavoriteId === item.id"
                        :aria-label="item.is_favorite ? '取消特别关注' : '标记为特别关注'"
                        :aria-pressed="item.is_favorite"
                        @click.stop="toggleFavorite(item)"
                      >
                        <Heart
                          class="h-4 w-4"
                          :class="{ 'fill-current': item.is_favorite }"
                        />
                      </button>
                    </TableCell>
                    <TableCell class="max-w-[220px] px-4 py-3">
                      <TooltipProvider :delay-duration="200">
                        <Tooltip>
                          <TooltipTrigger as-child>
                            <button
                              class="cell-ellipsis max-w-full text-left text-sm font-semibold text-primary hover:underline"
                              :aria-label="formatSecurityLabel(item.code, item.name)"
                              @click.stop="detailItem = item"
                            >
                              {{ formatSecurityLabel(item.code, item.name) }}
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>
                            {{ formatSecurityLabel(item.code, item.name) }}
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                      <div
                        v-if="item.tags.length"
                        class="mt-1 flex max-w-full flex-wrap gap-1"
                        data-testid="stock-tags"
                      >
                        <span
                          v-for="tag in item.tags"
                          :key="tag.id"
                          class="max-w-full rounded border border-border/60 bg-muted/60 px-1.5 py-0.5 text-[10px] leading-tight text-muted-foreground break-all"
                        >{{ tag.name }}</span>
                      </div>
                    </TableCell>
                    <TableCell class="px-4 py-3">
                      <span
                        class="rounded-lg border border-border/60 bg-background px-2 py-0.5 text-xs font-medium text-muted-foreground"
                      >
                        {{ marketLabel(item.market_type) }}
                      </span>
                    </TableCell>
                    <TableCell
                      class="whitespace-nowrap px-4 py-3 text-right font-medium tabular-nums text-foreground"
                    >
                      {{ formatQuoteNumber(getQuote(item.code, item.market_type)?.last_price) }}
                      <span
                        v-if="getQuote(item.code, item.market_type)?.quote_status === 'delayed'"
                        class="ml-1 text-xs text-warning"
                      >延迟</span>
                    </TableCell>
                    <TableCell
                      class="whitespace-nowrap px-4 py-3 text-right font-medium tabular-nums"
                      :class="movementClass(getQuote(item.code, item.market_type)?.change_amount)"
                    >
                      {{
                        formatSignedQuoteNumber(getQuote(item.code, item.market_type)?.change_amount)
                      }}
                    </TableCell>
                    <TableCell
                      class="whitespace-nowrap px-4 py-3 text-right font-medium tabular-nums"
                      :class="movementClass(getQuote(item.code, item.market_type)?.change_pct)"
                    >
                      {{
                        formatSignedQuoteNumber(getQuote(item.code, item.market_type)?.change_pct, '%')
                      }}
                    </TableCell>
                    <TableCell class="px-4 py-3">
                      <TrendStatus :trend="getQuote(item.code, item.market_type)?.trend_1m" />
                    </TableCell>
                    <TableCell class="px-4 py-3">
                      <PatternStatus
                        :pattern="getQuote(item.code, item.market_type)?.pattern_1m"
                        :now="currentTime"
                      />
                    </TableCell>
                    <TableCell class="px-4 py-3">
                      <IntradayDirectionStatus
                        :quote="getQuote(item.code, item.market_type)"
                        :market-type="item.market_type"
                        :now="currentTime"
                      />
                    </TableCell>
                    <TableCell class="px-4 py-3 text-right">
                      <DropdownMenu>
                        <DropdownMenuTrigger as-child>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label="自选股操作"
                            @click.stop
                          >
                            <MoreHorizontal />
                          </Button>
                        </DropdownMenuTrigger><DropdownMenuContent align="end">
                          <DropdownMenuItem @select="openEdit(item)">
                            <Pencil />编辑
                          </DropdownMenuItem><DropdownMenuSeparator /><DropdownMenuItem
                            class="text-destructive"
                            @select="openDelete(item)"
                          >
                            <Trash2 />删除
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                  <TableRow v-if="expandedCode === item.code">
                    <TableCell
                      :colspan="10"
                      class="max-w-0 p-3"
                    >
                      <IntradayStockPanel
                        :symbol="item.code"
                        :market="selectedMarket"
                      />
                    </TableCell>
                  </TableRow>
                </template>
              </template>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </template>

    <StockDetailDialog
      :stock="detailItem"
      :quote="detailItem ? getQuote(detailItem.code, detailItem.market_type) : undefined"
      kind="watchlist"
      @update:open="detailItem = null"
    />

    <!-- Add / Edit Dialog -->
    <Dialog
      :open="showDialog"
      @update:open="!saving && (showDialog = $event)"
    >
      <DialogContent class="max-w-md">
        <DialogHeader><DialogTitle>{{ editingId !== null ? '编辑自选股' : '添加自选股' }}</DialogTitle><DialogDescription>{{ editingId !== null ? '修改备注与分组标签。' : '搜索当前市场股票，可按需补充备注与分组标签。' }}</DialogDescription></DialogHeader>
        <div class="space-y-4 py-2">
          <div>
            <Label
              class="mb-2"
              for="watchlist-stock"
            >股票 *</Label>
            <FieldInput
              v-if="editingId !== null"
              id="watchlist-stock"
              :model-value="formStockQuery"
              readonly
            />
            <StockAutocomplete
              v-else
              v-model="formStockQuery"
              placeholder="搜索股票代码或名称"
              :teleported="false"
              :market="selectedMarket"
              @submit="handleStockAutocompleteSubmit"
            />
          </div>
          <div>
            <Label
              class="mb-2"
              for="watchlist-notes"
            >备注（可选）</Label>
            <FieldInput
              id="watchlist-notes"
              v-model="formNotes"
              placeholder="备注信息"
            />
          </div>
          <WatchListTagPicker
            v-model="formTags"
            :tags="tags"
            :disabled="saving"
          />
          <p
            v-if="formError"
            class="text-sm text-destructive"
          >
            {{ formError }}
          </p>
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            :disabled="saving"
            @click="closeDialog"
          >
            取消
          </Button>
          <Button
            variant="default"
            :disabled="saving"
            @click="save"
          >
            {{ saving ? '保存中…' : '保存' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <WatchListTagManager
      v-if="showTagManager"
      v-model:open="showTagManager"
      :tags="tags"
      @created="mergeTags([$event])"
      @renamed="renameTag"
      @deleted="deleteTag"
    />

    <AppConfirmDialog
      :open="showDeleteConfirm"
      title="删除自选股"
      :description="`确认从自选股中移除 ${deletingCode}？`"
      confirm-text="确认删除"
      destructive
      @update:open="showDeleteConfirm = $event"
      @confirm="confirmDelete"
    />
  </div>
</template>
