<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { signalsApi, type SignalListQuery } from '@/api/signals';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import LoadingButton from '@/components/app/LoadingButton.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import Pagination from '@/components/app/AppPagination.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type {
  SignalDirection,
  SignalEvaluationItem,
  SignalEvaluationPeriod,
  SignalItem,
  SignalMarket,
} from '@/types/signals';
import { formatDateTimeInDisplayTimezone, toUtcIsoString } from '@/utils/format';
import { formatSecurityLabel } from '@/utils/security';
import {
  SIGNAL_PERIODS,
  directionLabel,
  evaluationState,
  evaluationStatusLabel,
  formatReturnPct,
  formatSignalPrice,
  marketLabel,
  notApplicableReason,
  returnClass,
  signalTypeLabel,
} from '@/utils/signals';
import { Activity, Search } from 'lucide-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';

type BadgeVariant = 'default' | 'success' | 'warning' | 'destructive' | 'info';

const items = ref<SignalItem[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);

const selectedSignal = ref<SignalItem | null>(null);
const detailLoading = ref(false);
const detailError = ref<ParsedApiError | null>(null);

const filters = reactive<{
  market: SignalMarket | '';
  direction: SignalDirection | '';
  signalType: string;
  keyword: string;
  dateFrom: string;
  dateTo: string;
}>({
  market: '',
  direction: '',
  signalType: '',
  keyword: '',
  dateFrom: '',
  dateTo: '',
});

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)));
const hasFilters = computed(() =>
  Boolean(
    filters.market ||
      filters.direction ||
      filters.signalType.trim() ||
      filters.keyword.trim() ||
      filters.dateFrom ||
      filters.dateTo,
  ),
);

const marketOptions: Array<{ value: SignalMarket | ''; label: string }> = [
  { value: '', label: '全部市场' },
  { value: 'CN', label: 'A股' },
  { value: 'US', label: '美股' },
  { value: 'HK', label: '港股' },
];

const directionOptions: Array<{ value: SignalDirection | ''; label: string }> = [
  { value: '', label: '全部方向' },
  { value: 'bullish', label: '看多' },
  { value: 'bearish', label: '看空' },
  { value: 'sideways', label: '震荡' },
  { value: 'neutral', label: '中性' },
];

function dateStartIso(value: string): string {
  return toUtcIsoString(`${value}T00:00:00`);
}

function dateEndIso(value: string): string {
  return toUtcIsoString(`${value}T23:59:59`);
}

function buildQuery(targetPage = page.value): SignalListQuery {
  return {
    page: targetPage,
    pageSize: pageSize.value,
    market: filters.market || undefined,
    direction: filters.direction || undefined,
    signalType: filters.signalType.trim() || undefined,
    keyword: filters.keyword.trim() || undefined,
    signalAtFrom: filters.dateFrom ? dateStartIso(filters.dateFrom) : undefined,
    signalAtTo: filters.dateTo ? dateEndIso(filters.dateTo) : undefined,
  };
}

async function loadSignals(targetPage = page.value) {
  loading.value = true;
  error.value = null;
  try {
    const response = await signalsApi.list(buildQuery(targetPage));
    items.value = response.items;
    total.value = response.total;
    page.value = response.page;
    pageSize.value = response.pageSize;
  } catch (err) {
    error.value = getParsedApiError(err);
  } finally {
    loading.value = false;
  }
}

function submitFilters() {
  void loadSignals(1);
}

function resetFilters() {
  Object.assign(filters, {
    market: '',
    direction: '',
    signalType: '',
    keyword: '',
    dateFrom: '',
    dateTo: '',
  });
  void loadSignals(1);
}

function directionVariant(direction: string): BadgeVariant {
  if (direction === 'bullish') return 'destructive';
  if (direction === 'bearish') return 'success';
  if (direction === 'sideways') return 'warning';
  return 'default';
}

async function openDetail(item: SignalItem) {
  selectedSignal.value = item;
  detailLoading.value = true;
  detailError.value = null;
  try {
    selectedSignal.value = await signalsApi.get(item.id);
  } catch (err) {
    detailError.value = getParsedApiError(err);
  } finally {
    detailLoading.value = false;
  }
}

function closeDetail() {
  selectedSignal.value = null;
  detailError.value = null;
}

function periodItem(period: SignalEvaluationPeriod): SignalEvaluationItem | undefined {
  return selectedSignal.value?.evaluation[period];
}

function periodStatus(period: SignalEvaluationPeriod): string {
  if (!selectedSignal.value) return '待评估';
  const state = evaluationState(selectedSignal.value.evaluation, period);
  if (state === 'evaluated') return '已评价';
  if (state === 'not_applicable') return '不适用';
  if (state === 'invalid') return '数据异常';
  return '待评估';
}

onMounted(() => {
  void loadSignals(1);
});
</script>

<template>
  <div class="min-w-0 space-y-4">
    <header>
      <h2 class="text-lg font-semibold tracking-tight text-foreground">
        信号效果评估
      </h2>
      <p class="mt-1 text-xs leading-5 text-muted-foreground">
        展示信号产生后30分钟、1小时及后续交易日的客观价格表现，不代表完整交易策略收益。
      </p>
    </header>

    <Card>
      <CardHeader>
        <CardTitle>筛选条件</CardTitle><CardDescription>按市场、方向、信号类型、股票和日期范围筛选。</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          data-testid="signal-filters"
          @submit.prevent="submitFilters"
        >
          <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <FieldSelect
              :model-value="filters.market"
              label="市场"
              :options="marketOptions"
              @update:model-value="filters.market = $event as SignalMarket | ''"
            />
            <FieldSelect
              :model-value="filters.direction"
              label="方向"
              :options="directionOptions"
              @update:model-value="filters.direction = $event as SignalDirection | ''"
            />
            <FieldInput
              v-model="filters.signalType"
              label="信号类型"
              placeholder="输入原始信号类型"
            />
            <FieldInput
              v-model="filters.keyword"
              label="股票代码"
              placeholder="例如 NVDA"
            />
            <div class="grid grid-cols-2 gap-2 sm:col-span-2 xl:col-span-1">
              <AppDatePicker
                v-model="filters.dateFrom"
                label="开始日期"
              />
              <AppDatePicker
                v-model="filters.dateTo"
                label="结束日期"
              />
            </div>
          </div>
          <div class="mt-4 flex flex-wrap justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              @click="resetFilters"
            >
              重置
            </Button>
            <LoadingButton
              type="submit"
              variant="default"
              size="sm"
              :loading="loading"
            >
              <Search class="h-4 w-4" />
              查询
            </LoadingButton>
          </div>
        </form>
      </CardContent>
    </Card>

    <ApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重试"
      @dismiss="error = null"
      @action="loadSignals(page)"
    />

    <div
      v-if="loading && !items.length"
      class="space-y-2"
      aria-label="正在加载信号记录"
    >
      <Skeleton
        v-for="index in 5"
        :key="index"
        class="h-20 w-full"
      />
    </div>

    <Empty
      v-else-if="!items.length && !error"
      data-testid="signal-empty-state"
    >
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Activity />
        </EmptyMedia><EmptyTitle>{{ hasFilters ? '没有符合当前筛选条件的信号' : '暂无信号记录' }}</EmptyTitle><EmptyDescription>调整筛选条件或稍后等待新信号完成评价。</EmptyDescription>
      </EmptyHeader>
    </Empty>

    <template v-else>
      <div
        class="space-y-3 md:hidden"
        data-testid="signal-mobile-list"
      >
        <Card
          v-for="item in items"
          :key="item.id"
        >
          <CardHeader>
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="font-semibold text-foreground">
                  {{ formatSecurityLabel(item.code, item.name) }}
                  <span class="text-xs font-normal text-muted-foreground">{{
                    marketLabel(item.market)
                  }}</span>
                </p>
                <p class="mt-1 truncate text-sm text-muted-foreground">
                  {{ signalTypeLabel(item.signalType) }} · {{ item.signalVersion }}
                </p>
              </div>
              <Badge :variant="directionVariant(item.direction)">
                {{ directionLabel(item.direction) }}
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            <div class="flex items-end justify-between gap-3">
              <div>
                <p class="text-xs text-muted-foreground">
                  信号价格
                </p>
                <p class="font-mono text-sm font-medium">
                  {{ formatSignalPrice(item.signalPrice) }}
                </p>
              </div>
              <p class="text-right text-xs text-muted-foreground">
                {{ formatDateTimeInDisplayTimezone(item.signalAt) }}
              </p>
            </div>
            <div
              class="mt-3 grid grid-cols-2 gap-2"
              data-testid="signal-returns-grid"
            >
              <div
                v-for="period in SIGNAL_PERIODS"
                :key="period"
                class="rounded-lg bg-muted/50 px-2.5 py-2 text-xs"
              >
                <span class="text-muted-foreground">{{ period }}</span>
                <span
                  class="ml-2 font-mono"
                  :class="
                    evaluationState(item.evaluation, period) === 'evaluated'
                      ? returnClass(item.evaluation[period]?.returnPct)
                      : 'text-muted-foreground'
                  "
                >{{ evaluationStatusLabel(item.evaluation, period) }}</span>
              </div>
            </div>
          </CardContent>
          <CardContent class="pt-0">
            <Button
              variant="outline"
              size="sm"
              class="mt-3 w-full"
              @click="openDetail(item)"
            >
              查看详情
            </Button>
          </CardContent>
        </Card>
      </div>

      <div
        class="hidden overflow-x-auto rounded-xl border bg-card md:block"
      >
        <Table class="w-full min-w-[1020px] table-fixed text-left text-sm">
          <colgroup>
            <col class="w-[160px]" />
            <col class="w-[130px]" />
            <col class="w-[190px]" />
            <col class="w-[90px]" />
            <col class="w-[110px]" />
            <col class="w-[260px]" />
            <col class="w-[80px]" />
          </colgroup>
          <TableHeader class="border-b border-border/70 text-xs text-muted-foreground">
            <TableRow>
              <TableHead class="px-4 py-3 font-medium">
                信号时间
              </TableHead>
              <TableHead class="px-4 py-3 font-medium">
                市场 / 标的
              </TableHead>
              <TableHead class="px-4 py-3 font-medium">
                信号类型
              </TableHead>
              <TableHead class="px-4 py-3 font-medium">
                方向
              </TableHead>
              <TableHead class="px-4 py-3 text-right font-medium">
                信号价格
              </TableHead>
              <TableHead class="px-4 py-3 font-medium">
                未来涨幅
              </TableHead>
              <TableHead class="px-4 py-3 text-right font-medium">
                操作
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody class="divide-y divide-border/60">
            <TableRow
              v-for="item in items"
              :key="item.id"
              class="align-top hover:bg-muted/50"
            >
              <TableCell class="px-4 py-4 text-muted-foreground">
                {{ formatDateTimeInDisplayTimezone(item.signalAt) }}
              </TableCell>
              <TableCell class="px-4 py-4">
                <span class="text-xs text-muted-foreground">{{ marketLabel(item.market) }} ·</span>
                <span class="ml-1 font-semibold text-foreground">{{ formatSecurityLabel(item.code, item.name) }}</span>
              </TableCell>
              <TableCell class="px-4 py-4">
                <p class="font-medium text-foreground">
                  {{ signalTypeLabel(item.signalType) }}
                </p>
                <p class="mt-0.5 text-xs text-muted-foreground">
                  {{ item.signalVersion }}
                </p>
              </TableCell>
              <TableCell class="px-4 py-4">
                <Badge :variant="directionVariant(item.direction)">
                  {{ directionLabel(item.direction) }}
                </Badge>
              </TableCell>
              <TableCell class="px-4 py-4 text-right font-mono text-foreground">
                {{ formatSignalPrice(item.signalPrice) }}
              </TableCell>
              <TableCell class="px-4 py-4">
                <div
                  class="grid grid-cols-2 gap-x-4 gap-y-2"
                  data-testid="signal-returns-grid"
                >
                  <div
                    v-for="period in SIGNAL_PERIODS"
                    :key="period"
                    class="grid grid-cols-[34px_minmax(0,1fr)] items-center gap-1 text-xs"
                  >
                    <span class="font-medium text-muted-foreground">{{ period }}</span>
                    <span
                      :class="[
                        'whitespace-nowrap font-mono',
                        evaluationState(item.evaluation, period) === 'evaluated'
                          ? returnClass(item.evaluation[period]?.returnPct)
                          : 'text-muted-foreground',
                      ]"
                    >
                      {{ evaluationStatusLabel(item.evaluation, period) }}
                    </span>
                  </div>
                </div>
              </TableCell>
              <TableCell class="px-4 py-4 text-right">
                <button
                  type="button"
                  class="whitespace-nowrap text-xs font-medium text-primary hover:underline"
                  @click="openDetail(item)"
                >
                  查看详情
                </button>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>

      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p class="text-xs text-muted-foreground">
          共 {{ total }} 条，当前第 {{ page }} 页
        </p>
        <Pagination
          :current-page="page"
          :total-pages="totalPages"
          @page-change="loadSignals"
        />
      </div>
    </template>

    <Sheet
      :open="selectedSignal !== null"
      @update:open="closeDetail"
    >
      <SheetContent class="flex w-full flex-col p-0 sm:max-w-3xl">
        <SheetHeader class="p-6 text-left">
          <SheetTitle>信号评估详情</SheetTitle><SheetDescription>查看信号元数据与各评价周期的客观表现。</SheetDescription>
        </SheetHeader>
        <Separator />
        <ScrollArea class="min-h-0 flex-1">
          <div class="p-6">
            <div
              v-if="detailLoading"
              class="space-y-3"
              aria-label="正在加载信号详情"
            >
              <Skeleton
                v-for="index in 5"
                :key="index"
                class="h-12 w-full"
              />
            </div>
            <ApiErrorAlert
              v-else-if="detailError"
              :error="detailError"
              @dismiss="closeDetail"
            />
            <div
              v-else-if="selectedSignal"
              class="space-y-6"
            >
              <dl class="grid gap-3 rounded-lg border bg-muted/40 p-4 sm:grid-cols-2">
                <div>
                  <dt class="text-xs text-muted-foreground">
                    Signal ID
                  </dt>
                  <dd class="mt-1 text-sm">
                    {{ selectedSignal.id }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    市场
                  </dt>
                  <dd class="mt-1 text-sm">
                    {{ marketLabel(selectedSignal.market) }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    股票代码
                  </dt>
                  <dd class="mt-1 text-sm font-semibold">
                    {{ formatSecurityLabel(selectedSignal.code, selectedSignal.name) }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    信号类型
                  </dt>
                  <dd class="mt-1 text-sm">
                    {{ signalTypeLabel(selectedSignal.signalType) }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    原始 signal_type
                  </dt>
                  <dd class="mt-1 break-all text-sm">
                    {{ selectedSignal.signalType || '—' }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    信号版本
                  </dt>
                  <dd class="mt-1 text-sm">
                    {{ selectedSignal.signalVersion }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    方向
                  </dt>
                  <dd class="mt-1 text-sm">
                    {{ directionLabel(selectedSignal.direction) }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    信号价格
                  </dt>
                  <dd class="mt-1 font-mono text-sm">
                    {{ formatSignalPrice(selectedSignal.signalPrice) }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    信号时间
                  </dt>
                  <dd class="mt-1 text-sm">
                    {{ formatDateTimeInDisplayTimezone(selectedSignal.signalAt) }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    创建时间
                  </dt>
                  <dd class="mt-1 text-sm">
                    {{ formatDateTimeInDisplayTimezone(selectedSignal.createdAt) }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    更新时间
                  </dt>
                  <dd class="mt-1 text-sm">
                    {{ formatDateTimeInDisplayTimezone(selectedSignal.updatedAt) }}
                  </dd>
                </div>
              </dl>

              <div>
                <h3 class="mb-3 text-sm font-semibold text-foreground">
                  各周期表现
                </h3>
                <div class="grid gap-3 sm:grid-cols-2">
                  <Card
                    v-for="period in SIGNAL_PERIODS"
                    :key="period"
                  >
                    <CardHeader>
                      <div class="flex items-center justify-between gap-3">
                        <CardTitle class="text-base">
                          {{ period }}
                        </CardTitle>
                        <Badge :variant="periodStatus(period) === '已评价' ? 'info' : 'default'">
                          {{ periodStatus(period) }}
                        </Badge>
                      </div>
                    </CardHeader><CardContent>
                      <dl
                        v-if="evaluationState(selectedSignal.evaluation, period) === 'evaluated'"
                        class="space-y-2 text-sm"
                      >
                        <div class="flex justify-between gap-3">
                          <dt class="text-muted-foreground">
                            目标价格
                          </dt>
                          <dd class="font-mono">
                            {{ formatSignalPrice(periodItem(period)?.price) }}
                          </dd>
                        </div>
                        <div class="flex justify-between gap-3">
                          <dt class="text-muted-foreground">
                            收益率
                          </dt>
                          <dd :class="returnClass(periodItem(period)?.returnPct)">
                            {{ formatReturnPct(periodItem(period)?.returnPct) }}
                          </dd>
                        </div>
                        <div class="flex justify-between gap-3">
                          <dt class="text-muted-foreground">
                            期间最大涨幅
                          </dt>
                          <dd :class="returnClass(periodItem(period)?.maxReturnPct)">
                            {{ formatReturnPct(periodItem(period)?.maxReturnPct) }}
                          </dd>
                        </div>
                        <div class="flex justify-between gap-3">
                          <dt class="text-muted-foreground">
                            期间最小涨幅
                          </dt>
                          <dd :class="returnClass(periodItem(period)?.minReturnPct)">
                            {{ formatReturnPct(periodItem(period)?.minReturnPct) }}
                          </dd>
                        </div>
                        <div class="flex justify-between gap-3">
                          <dt class="text-muted-foreground">
                            评价时间
                          </dt>
                          <dd class="text-right">
                            {{ formatDateTimeInDisplayTimezone(periodItem(period)?.evaluatedAt) }}
                          </dd>
                        </div>
                      </dl>
                      <dl
                        v-else-if="evaluationState(selectedSignal.evaluation, period) === 'not_applicable'"
                        class="space-y-2 text-sm"
                      >
                        <div class="flex justify-between gap-3">
                          <dt class="text-muted-foreground">
                            状态
                          </dt>
                          <dd>不适用</dd>
                        </div>
                        <div class="flex justify-between gap-3">
                          <dt class="text-muted-foreground">
                            原因
                          </dt>
                          <dd>{{ notApplicableReason(periodItem(period)) }}</dd>
                        </div>
                      </dl>
                      <p
                        v-else-if="evaluationState(selectedSignal.evaluation, period) === 'pending'"
                        class="text-sm text-muted-foreground"
                      >
                        状态：待评估
                      </p>
                      <p
                        v-else
                        class="text-sm text-muted-foreground"
                      >
                        状态：数据异常
                      </p>
                    </CardContent>
                  </Card>
                </div>
              </div>
            </div>
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  </div>
</template>
