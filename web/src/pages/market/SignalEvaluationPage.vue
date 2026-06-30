<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { signalsApi, type SignalListQuery } from '@/api/signals';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Badge from '@/components/common/Badge.vue';
import Button from '@/components/common/Button.vue';
import Drawer from '@/components/common/Drawer.vue';
import Input from '@/components/common/Input.vue';
import Pagination from '@/components/common/Pagination.vue';
import type {
  SignalDirection,
  SignalEvaluationItem,
  SignalEvaluationPeriod,
  SignalItem,
  SignalMarket,
} from '@/types/signals';
import { formatDateTimeInDisplayTimezone, toUtcIsoString } from '@/utils/format';
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
import { Activity, Search, SlidersHorizontal } from 'lucide-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info';

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
    filters.market
      || filters.direction
      || filters.signalType.trim()
      || filters.keyword.trim()
      || filters.dateFrom
      || filters.dateTo,
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
  if (direction === 'bullish') return 'danger';
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
    <header class="flex items-start gap-3">
      <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-primary-gradient text-primary-foreground shadow-soft-card">
        <Activity class="h-5 w-5" />
      </div>
      <div>
        <h2 class="text-lg font-semibold text-foreground">
          信号效果评估
        </h2>
        <p class="mt-1 text-xs leading-5 text-secondary-text">
          展示信号产生后30分钟、1小时及后续交易日的客观价格表现，不代表完整交易策略收益。
        </p>
      </div>
    </header>

    <form
      class="rounded-2xl border border-border/70 bg-card/94 p-4 shadow-soft-card"
      data-testid="signal-filters"
      @submit.prevent="submitFilters"
    >
      <div class="mb-3 flex items-center gap-2 text-sm font-medium text-foreground">
        <SlidersHorizontal class="h-4 w-4 text-primary" />
        筛选条件
      </div>
      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <label class="block text-xs text-muted-text">
          <span class="mb-1.5 block">市场</span>
          <select
            v-model="filters.market"
            class="input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-foreground outline-none"
          >
            <option
              v-for="option in marketOptions"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </option>
          </select>
        </label>
        <label class="block text-xs text-muted-text">
          <span class="mb-1.5 block">方向</span>
          <select
            v-model="filters.direction"
            class="input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-3 text-sm text-foreground outline-none"
          >
            <option
              v-for="option in directionOptions"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </option>
          </select>
        </label>
        <Input
          v-model="filters.signalType"
          label="信号类型"
          placeholder="输入原始信号类型"
        />
        <Input
          v-model="filters.keyword"
          label="股票代码"
          placeholder="例如 NVDA"
        />
        <div class="grid grid-cols-2 gap-2 sm:col-span-2 xl:col-span-1">
          <Input
            v-model="filters.dateFrom"
            label="开始日期"
            type="date"
          />
          <Input
            v-model="filters.dateTo"
            label="结束日期"
            type="date"
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
        <Button
          type="submit"
          variant="primary"
          size="sm"
          :is-loading="loading"
        >
          <Search class="h-4 w-4" />
          查询
        </Button>
      </div>
    </form>

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
      <div
        v-for="index in 5"
        :key="index"
        class="h-20 animate-pulse rounded-xl bg-card"
      />
    </div>

    <div
      v-else-if="!items.length && !error"
      class="rounded-2xl border border-dashed border-border/70 px-6 py-16 text-center"
      data-testid="signal-empty-state"
    >
      <Activity class="mx-auto h-10 w-10 text-muted-text/40" />
      <p class="mt-3 text-sm text-secondary-text">
        {{ hasFilters ? '没有符合当前筛选条件的信号' : '暂无信号记录' }}
      </p>
    </div>

    <template v-else>
      <div class="overflow-x-auto rounded-2xl border border-border/70 bg-card/94 shadow-soft-card">
        <table class="w-full min-w-[1020px] table-fixed text-left text-sm">
          <colgroup>
            <col class="w-[160px]" />
            <col class="w-[130px]" />
            <col class="w-[190px]" />
            <col class="w-[90px]" />
            <col class="w-[110px]" />
            <col class="w-[260px]" />
            <col class="w-[80px]" />
          </colgroup>
          <thead class="border-b border-border/70 text-xs text-muted-text">
            <tr>
              <th class="px-4 py-3 font-medium">
                信号时间
              </th>
              <th class="px-4 py-3 font-medium">
                市场 / 标的
              </th>
              <th class="px-4 py-3 font-medium">
                信号类型
              </th>
              <th class="px-4 py-3 font-medium">
                方向
              </th>
              <th class="px-4 py-3 text-right font-medium">
                信号价格
              </th>
              <th class="px-4 py-3 font-medium">
                未来涨幅
              </th>
              <th class="px-4 py-3 text-right font-medium">
                操作
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border/60">
            <tr
              v-for="item in items"
              :key="item.id"
              class="align-top hover:bg-hover/50"
            >
              <td class="px-4 py-4 text-secondary-text">
                {{ formatDateTimeInDisplayTimezone(item.signalAt) }}
              </td>
              <td class="px-4 py-4">
                <span class="text-xs text-muted-text">{{ marketLabel(item.market) }} ·</span>
                <span class="ml-1 font-semibold text-foreground">{{ item.code }}</span>
              </td>
              <td class="px-4 py-4">
                <p class="font-medium text-foreground">
                  {{ signalTypeLabel(item.signalType) }}
                </p>
                <p class="mt-0.5 text-xs text-muted-text">
                  {{ item.signalVersion }}
                </p>
              </td>
              <td class="px-4 py-4">
                <Badge :variant="directionVariant(item.direction)">
                  {{ directionLabel(item.direction) }}
                </Badge>
              </td>
              <td class="px-4 py-4 text-right font-mono text-foreground">
                {{ formatSignalPrice(item.signalPrice) }}
              </td>
              <td class="px-4 py-4">
                <div
                  class="grid grid-cols-2 gap-x-4 gap-y-2"
                  data-testid="signal-returns-grid"
                >
                  <div
                    v-for="period in SIGNAL_PERIODS"
                    :key="period"
                    class="grid grid-cols-[34px_minmax(0,1fr)] items-center gap-1 text-xs"
                  >
                    <span class="font-medium text-muted-text">{{ period }}</span>
                    <span
                      :class="[
                        'whitespace-nowrap font-mono',
                        evaluationState(item.evaluation, period) === 'evaluated'
                          ? returnClass(item.evaluation[period]?.returnPct)
                          : 'text-secondary-text',
                      ]"
                    >
                      {{ evaluationStatusLabel(item.evaluation, period) }}
                    </span>
                  </div>
                </div>
              </td>
              <td class="px-4 py-4 text-right">
                <button
                  type="button"
                  class="whitespace-nowrap text-xs font-medium text-primary hover:underline"
                  @click="openDetail(item)"
                >
                  查看详情
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p class="text-xs text-muted-text">
          共 {{ total }} 条，当前第 {{ page }} 页
        </p>
        <Pagination
          :current-page="page"
          :total-pages="totalPages"
          @page-change="loadSignals"
        />
      </div>
    </template>

    <Drawer
      :is-open="selectedSignal !== null"
      title="信号评估详情"
      width="max-w-3xl"
      @close="closeDetail"
    >
      <div
        v-if="detailLoading"
        class="space-y-3"
        aria-label="正在加载信号详情"
      >
        <div
          v-for="index in 5"
          :key="index"
          class="h-12 animate-pulse rounded-xl bg-elevated"
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
        <dl class="grid gap-3 rounded-2xl border border-border/70 bg-elevated/45 p-4 sm:grid-cols-2">
          <div>
            <dt class="text-xs text-muted-text">
              Signal ID
            </dt><dd class="mt-1 text-sm">
              {{ selectedSignal.id }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-text">
              市场
            </dt><dd class="mt-1 text-sm">
              {{ marketLabel(selectedSignal.market) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-text">
              股票代码
            </dt><dd class="mt-1 text-sm font-semibold">
              {{ selectedSignal.code }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-text">
              信号类型
            </dt><dd class="mt-1 text-sm">
              {{ signalTypeLabel(selectedSignal.signalType) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-text">
              原始 signal_type
            </dt><dd class="mt-1 break-all text-sm">
              {{ selectedSignal.signalType || '—' }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-text">
              信号版本
            </dt><dd class="mt-1 text-sm">
              {{ selectedSignal.signalVersion }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-text">
              方向
            </dt><dd class="mt-1 text-sm">
              {{ directionLabel(selectedSignal.direction) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-text">
              信号价格
            </dt><dd class="mt-1 font-mono text-sm">
              {{ formatSignalPrice(selectedSignal.signalPrice) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-text">
              信号时间
            </dt><dd class="mt-1 text-sm">
              {{ formatDateTimeInDisplayTimezone(selectedSignal.signalAt) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-text">
              创建时间
            </dt><dd class="mt-1 text-sm">
              {{ formatDateTimeInDisplayTimezone(selectedSignal.createdAt) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-text">
              更新时间
            </dt><dd class="mt-1 text-sm">
              {{ formatDateTimeInDisplayTimezone(selectedSignal.updatedAt) }}
            </dd>
          </div>
        </dl>

        <div>
          <h3 class="mb-3 text-sm font-semibold text-foreground">
            各周期表现
          </h3>
          <div class="grid gap-3 sm:grid-cols-2">
            <section
              v-for="period in SIGNAL_PERIODS"
              :key="period"
              class="rounded-2xl border border-border/70 bg-card p-4"
            >
              <div class="mb-3 flex items-center justify-between gap-3">
                <h4 class="font-semibold text-foreground">
                  {{ period }}
                </h4>
                <Badge
                  :variant="periodStatus(period) === '已评价' ? 'info' : 'default'"
                >
                  {{ periodStatus(period) }}
                </Badge>
              </div>
              <dl
                v-if="evaluationState(selectedSignal.evaluation, period) === 'evaluated'"
                class="space-y-2 text-sm"
              >
                <div class="flex justify-between gap-3">
                  <dt class="text-muted-text">
                    目标价格
                  </dt><dd class="font-mono">
                    {{ formatSignalPrice(periodItem(period)?.price) }}
                  </dd>
                </div>
                <div class="flex justify-between gap-3">
                  <dt class="text-muted-text">
                    收益率
                  </dt><dd :class="returnClass(periodItem(period)?.returnPct)">
                    {{ formatReturnPct(periodItem(period)?.returnPct) }}
                  </dd>
                </div>
                <div class="flex justify-between gap-3">
                  <dt class="text-muted-text">
                    期间最大涨幅
                  </dt><dd :class="returnClass(periodItem(period)?.maxReturnPct)">
                    {{ formatReturnPct(periodItem(period)?.maxReturnPct) }}
                  </dd>
                </div>
                <div class="flex justify-between gap-3">
                  <dt class="text-muted-text">
                    期间最小涨幅
                  </dt><dd :class="returnClass(periodItem(period)?.minReturnPct)">
                    {{ formatReturnPct(periodItem(period)?.minReturnPct) }}
                  </dd>
                </div>
                <div class="flex justify-between gap-3">
                  <dt class="text-muted-text">
                    评价时间
                  </dt><dd class="text-right">
                    {{ formatDateTimeInDisplayTimezone(periodItem(period)?.evaluatedAt) }}
                  </dd>
                </div>
              </dl>
              <dl
                v-else-if="evaluationState(selectedSignal.evaluation, period) === 'not_applicable'"
                class="space-y-2 text-sm"
              >
                <div class="flex justify-between gap-3">
                  <dt class="text-muted-text">
                    状态
                  </dt><dd>不适用</dd>
                </div>
                <div class="flex justify-between gap-3">
                  <dt class="text-muted-text">
                    原因
                  </dt><dd>{{ notApplicableReason(periodItem(period)) }}</dd>
                </div>
              </dl>
              <p
                v-else-if="evaluationState(selectedSignal.evaluation, period) === 'pending'"
                class="text-sm text-secondary-text"
              >
                状态：待评估
              </p>
              <p
                v-else
                class="text-sm text-secondary-text"
              >
                状态：数据异常
              </p>
            </section>
          </div>
        </div>
      </div>
    </Drawer>
  </div>
</template>
