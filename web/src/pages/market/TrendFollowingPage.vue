<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { RefreshCcw } from 'lucide-vue-next';
import { toast } from 'vue-sonner';
import { trendFollowingApi } from '@/api/trendFollowing';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import IndicatorLabel from '@/components/app/IndicatorHelpLabel.vue';
import LoadingButton from '@/components/app/LoadingButton.vue';
import { trendIndicatorDescriptions as descriptions } from '@/components/trend-following/indicatorDescriptions';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type {
  TrendAction,
  TrendChange,
  TrendDetailResponse,
  TrendMarket,
  TrendPortfolioPosition,
  TrendPortfolioResponse,
  TrendRankingChanges,
  TrendSnapshot,
  TrendState,
  TrendSummary,
} from '@/types/trendFollowing';
import { formatMarketCurrencyAmount } from '@/utils/marketCurrency';

const emptySummary = (): TrendSummary => ({
  market: 'CN', tradeDate: '', universeKey: 'cn_csi300_csi500', benchmarkCode: '510300.SH',
  marketRegime: 'NEUTRAL', marketScore: 0, suggestedMaxExposure: 0, universeSize: 0,
  dataReadyCount: 0, dataCoverage: 0, rankableCount: 0, candidateCount: 0, entryCount: 0,
  addCount: 0, holdCount: 0, reduceCount: 0, exitCount: 0, warnings: [], features: {},
  scoreBreakdown: {}, generatedAt: '',
});
const emptyPortfolio = (portfolioMarket: TrendMarket = 'CN'): TrendPortfolioResponse => ({
  market: portfolioMarket, tradeDate: '', marketRegime: 'NEUTRAL', maxExposure: 0,
  currentExposure: 0, remainingExposure: 0, positionCount: 0, positions: [],
});
const market = ref<TrendMarket>('CN');
const selectedDate = ref('');
const availableDates = ref<string[]>([]);
const summary = ref<TrendSummary>(emptySummary());
const items = ref<TrendSnapshot[]>([]);
const candidates = ref<TrendSnapshot[]>([]);
const portfolio = ref<TrendPortfolioResponse>(emptyPortfolio());
const changes = ref<TrendRankingChanges | null>(null);
const loading = ref(true);
const running = ref(false);
const error = ref<ParsedApiError | null>(null);
const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref<TrendDetailResponse | null>(null);
const detailError = ref<ParsedApiError | null>(null);
const sortKey = ref<'rank' | 'alphaScore' | 'trendScore' | 'rsScore' | 'breakoutScore'>('rank');
let generation = 0;

const scope = computed(() => market.value === 'CN' ? '沪深300 + 中证500' : 'S&P 500');
const sortedItems = computed(() => [...items.value].sort((left, right) => {
  if (sortKey.value === 'rank') return left.rank - right.rank;
  return right[sortKey.value] - left[sortKey.value] || left.code.localeCompare(right.code);
}));
const cards = computed(() => [
  ['Market Regime', summary.value.marketRegime, descriptions.marketRegime],
  ['Market Score', score(summary.value.marketScore), descriptions.marketScore],
  ['最大理论风险敞口', pct(summary.value.suggestedMaxExposure), descriptions.maxExposure],
  ['Universe Size', summary.value.universeSize, descriptions.universeSize],
  ['Data Coverage', pct(summary.value.dataCoverage), descriptions.dataCoverage],
  ['Rankable', summary.value.rankableCount, descriptions.rankable],
  ['Candidate', summary.value.candidateCount, descriptions.candidate],
  ['ENTRY', summary.value.entryCount, descriptions.lifecycleCount],
  ['ADD', summary.value.addCount, descriptions.lifecycleCount],
  ['HOLD', summary.value.holdCount, descriptions.lifecycleCount],
  ['REDUCE', summary.value.reduceCount, descriptions.lifecycleCount],
  ['EXIT', summary.value.exitCount, descriptions.lifecycleCount],
]);
const changeGroups = computed(() => [
  { label: 'New Candidates', items: changes.value?.newCandidates ?? [], variant: 'info' as const },
  { label: 'New Weakening', items: changes.value?.newWeakening ?? [], variant: 'warning' as const },
  { label: 'New REDUCE', items: changes.value?.newReduces ?? [], variant: 'destructive' as const },
  { label: 'New EXIT', items: changes.value?.newExits ?? [], variant: 'destructive' as const },
]);
const exposureProgress = computed(() => {
  if (portfolio.value.maxExposure <= 0) return 0;
  return Math.min(100, (portfolio.value.currentExposure / portfolio.value.maxExposure) * 100);
});

function score(value: number | null | undefined) { return value == null ? '—' : value.toFixed(1); }
function scoreDelta(value: number | null | undefined) { return value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(1)}`; }
function rankDelta(value: number | null | undefined) { return value == null ? '—' : `${value > 0 ? '+' : ''}${value}`; }
function pct(value: number | null | undefined) { return value == null ? '—' : `${(value * 100).toFixed(1)}%`; }
function price(value: number | null | undefined) {
  return value == null ? '—' : formatMarketCurrencyAmount(value, market.value);
}
function stateText(state: TrendState) {
  return ({ IDLE: '空闲', WATCHING: '观察', CANDIDATE: '候选', ENTRY: '建议入场', PYRAMIDING: '加仓中',
    HOLDING: '继续持有', WEAKENING: '趋势弱化', REDUCE: '建议减仓', EXIT: '退出' })[state];
}
function actionText(action: TrendAction) {
  return ({ WATCH: '观察', PENDING_ENTRY: '等待入场', PENDING_ADD: '等待加仓', PENDING_REDUCE: '等待减仓',
    PENDING_EXIT: '等待退出', ENTRY: '已入场', ADD: '已加仓', HOLD: '继续持有',
    STOP_ADD: '停止加仓', REDUCE: '已减仓', EXIT: '已退出', EXPOSURE_BLOCKED: '风险限制' })[action];
}
function badgeVariant(value: TrendState | TrendAction | string): 'default' | 'success' | 'warning' | 'destructive' | 'info' | 'outline' {
  if (['ENTRY', 'ADD', 'PYRAMIDING', 'RISK_ON'].includes(value)) return 'success';
  if (['EXIT', 'REDUCE', 'RISK_OFF'].includes(value)) return 'destructive';
  if (['WEAKENING', 'STOP_ADD', 'NEUTRAL', 'EXPOSURE_BLOCKED', 'PENDING_REDUCE', 'PENDING_EXIT'].includes(value)) return 'warning';
  if (['HOLD', 'HOLDING'].includes(value)) return 'default';
  if (['CANDIDATE', 'PENDING_ENTRY', 'PENDING_ADD'].includes(value)) return 'info';
  return 'outline';
}
function transitionText(change: TrendChange) {
  return `${change.previousState ?? 'NEW'} → ${change.current.state}`;
}
async function load(refreshDates = false) {
  const current = ++generation;
  loading.value = true;
  error.value = null;
  try {
    if (refreshDates || !availableDates.value.length) {
      const dates = await trendFollowingApi.dates(market.value);
      if (current !== generation) return;
      availableDates.value = dates.items;
    }
    const ranking = await trendFollowingApi.ranking(market.value, selectedDate.value || undefined);
    if (current !== generation) return;
    summary.value = ranking;
    items.value = ranking.items;
    changes.value = ranking.changes ?? null;
    selectedDate.value = ranking.tradeDate;
    const [candidateResult, portfolioResult] = await Promise.all([
      trendFollowingApi.candidates(market.value, ranking.tradeDate),
      trendFollowingApi.portfolio(market.value, ranking.tradeDate),
    ]);
    if (current === generation) {
      candidates.value = candidateResult.items;
      portfolio.value = portfolioResult;
    }
  } catch (reason) {
    if (current === generation) {
      error.value = getParsedApiError(reason);
      items.value = [];
      candidates.value = [];
      portfolio.value = emptyPortfolio(market.value);
      changes.value = null;
    }
  } finally {
    if (current === generation) loading.value = false;
  }
}
async function runLatest() {
  running.value = true;
  try {
    const result = await trendFollowingApi.run(market.value);
    toast.success(`趋势跟踪任务已提交：${result.taskId}`);
  } catch (reason) {
    error.value = getParsedApiError(reason);
  } finally {
    running.value = false;
  }
}
async function openDetail(item: Pick<TrendSnapshot, 'code'> & { tradeDate?: string }) {
  detailOpen.value = true;
  detailLoading.value = true;
  detailError.value = null;
  detail.value = null;
  try {
    detail.value = await trendFollowingApi.detail(
      item.code,
      market.value,
      60,
      selectedDate.value || item.tradeDate,
    );
  } catch (reason) {
    detailError.value = getParsedApiError(reason);
  } finally {
    detailLoading.value = false;
  }
}
function openPositionDetail(position: TrendPortfolioPosition) {
  void openDetail({ code: position.code, tradeDate: portfolio.value.tradeDate });
}
watch(market, () => {
  selectedDate.value = '';
  availableDates.value = [];
  detailOpen.value = false;
  summary.value = { ...emptySummary(), market: market.value };
  portfolio.value = emptyPortfolio(market.value);
  void load(true);
});
onMounted(() => void load(true));
</script>

<template>
  <div
    class="min-w-0 space-y-4"
    data-testid="trend-following-page"
  >
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold">
          趋势跟踪
        </h2>
        <p class="mt-1 text-xs text-muted-foreground">
          {{ scope }} · Research Signal / 策略模型建议，不是用户真实交易指令。
        </p>
      </div>
      <div class="flex flex-wrap items-end gap-2">
        <NativeSelect
          v-model="market"
          class="h-10"
          aria-label="市场"
          data-testid="trend-market"
        >
          <NativeSelectOption value="CN">
            A股
          </NativeSelectOption>
          <NativeSelectOption value="US">
            美股
          </NativeSelectOption>
        </NativeSelect>
        <AppDatePicker
          :model-value="selectedDate"
          label="交易日"
          :available-dates="availableDates"
          :clearable="false"
          :disabled="loading"
          class="w-56"
          data-testid="trend-date"
          @update:model-value="value => { selectedDate = value; load(); }"
        />
        <Button
          variant="outline"
          class="h-10"
          data-testid="trend-refresh"
          :disabled="loading"
          @click="load(true)"
        >
          <RefreshCcw class="size-4" />刷新
        </Button>
        <LoadingButton
          class="h-10"
          :loading="running"
          loading-text="提交中…"
          data-testid="trend-run-latest"
          @click="runLatest"
        >
          运行最新数据
        </LoadingButton>
      </div>
    </header>

    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div
      v-if="summary.warnings.length"
      role="alert"
      class="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200"
    >
      {{ summary.warnings.join('；') }}
    </div>
    <div
      v-if="loading"
      class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
    >
      <Skeleton
        v-for="index in 8"
        :key="index"
        class="h-20"
      />
    </div>
    <div
      v-else
      class="grid gap-3 grid-cols-2 md:grid-cols-3 xl:grid-cols-6"
      data-testid="trend-summary"
    >
      <Card
        v-for="card in cards"
        :key="String(card[0])"
      >
        <CardContent class="p-3">
          <IndicatorLabel
            :label="String(card[0])"
            :description="String(card[2])"
            wrap
          />
          <strong class="mt-1 block text-lg">{{ card[1] }}</strong>
        </CardContent>
      </Card>
    </div>

    <Card data-testid="trend-portfolio">
      <CardHeader>
        <CardTitle>当前理论持仓</CardTitle>
        <CardDescription>
          {{ portfolio.tradeDate || summary.tradeDate || '—' }} · {{ portfolio.marketRegime }} · 由趋势跟踪 Snapshot 推导，不读取用户真实持仓、账户或资金数据。
        </CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div
          v-if="loading"
          class="grid gap-3 grid-cols-2 lg:grid-cols-4"
        >
          <Skeleton
            v-for="index in 4"
            :key="index"
            class="h-20"
          />
        </div>
        <template v-else>
          <div class="grid gap-3 grid-cols-2 lg:grid-cols-4">
            <div class="rounded-md border p-3">
              <span class="text-xs text-muted-foreground">当前理论仓位</span>
              <strong class="mt-1 block text-lg">{{ pct(portfolio.currentExposure) }}</strong>
            </div>
            <div class="rounded-md border p-3">
              <span class="text-xs text-muted-foreground">最大允许敞口</span>
              <strong class="mt-1 block text-lg">{{ pct(portfolio.maxExposure) }}</strong>
            </div>
            <div class="rounded-md border p-3">
              <span class="text-xs text-muted-foreground">剩余可用敞口</span>
              <strong class="mt-1 block text-lg">{{ pct(portfolio.remainingExposure) }}</strong>
            </div>
            <div class="rounded-md border p-3">
              <span class="text-xs text-muted-foreground">当前持仓</span>
              <strong class="mt-1 block text-lg">{{ portfolio.positionCount }}只</strong>
            </div>
          </div>
          <div
            class="space-y-2"
            data-testid="trend-portfolio-progress"
          >
            <div class="flex items-center justify-between gap-3 text-xs text-muted-foreground">
              <span>当前仓位 {{ pct(portfolio.currentExposure) }} / 最大敞口 {{ pct(portfolio.maxExposure) }}</span>
              <span>{{ exposureProgress.toFixed(1) }}%</span>
            </div>
            <div
              class="h-2 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label="理论仓位占最大敞口比例"
              :aria-valuenow="exposureProgress"
              aria-valuemin="0"
              aria-valuemax="100"
            >
              <div
                class="h-full rounded-full bg-primary transition-[width]"
                :style="{ width: `${exposureProgress}%` }"
              />
            </div>
          </div>
          <Empty v-if="!portfolio.positions.length">
            <EmptyHeader>
              <EmptyTitle>当前无理论持仓</EmptyTitle>
              <EmptyDescription>所选交易日没有处于有效持仓状态且 Units 大于 0 的股票。</EmptyDescription>
            </EmptyHeader>
          </Empty>
          <ScrollArea
            v-else
            class="w-full"
          >
            <Table class="min-w-[1650px]">
              <TableHeader>
                <TableRow>
                  <TableHead>股票</TableHead><TableHead>State</TableHead><TableHead>Action</TableHead>
                  <TableHead>Units</TableHead><TableHead>单位仓位</TableHead><TableHead>当前仓位</TableHead>
                  <TableHead>入场价</TableHead><TableHead>当前价</TableHead><TableHead>下一动作</TableHead>
                  <TableHead>入场日期</TableHead><TableHead>初始止损</TableHead><TableHead>跟踪止损</TableHead>
                  <TableHead>下次加仓价</TableHead><TableHead>退出线</TableHead><TableHead>Alpha</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow
                  v-for="position in portfolio.positions"
                  :key="position.code"
                  class="cursor-pointer"
                  data-testid="trend-position-row"
                  @click="openPositionDetail(position)"
                >
                  <TableCell><strong class="block">{{ position.name }}</strong><span class="font-mono text-xs text-muted-foreground">{{ position.code }}</span></TableCell>
                  <TableCell>
                    <Badge :variant="badgeVariant(position.state)">
                      {{ stateText(position.state) }}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge :variant="badgeVariant(position.action)">
                      {{ actionText(position.action) }}
                    </Badge>
                  </TableCell>
                  <TableCell>{{ position.units }}</TableCell><TableCell>{{ pct(position.unitWeight) }}</TableCell>
                  <TableCell class="font-semibold text-primary">
                    {{ pct(position.positionWeight) }}
                  </TableCell>
                  <TableCell>{{ price(position.entryPrice) }}</TableCell><TableCell>{{ price(position.referencePrice) }}</TableCell>
                  <TableCell>{{ position.pendingAction ? actionText(position.pendingAction) : '—' }}</TableCell>
                  <TableCell>{{ position.openedAt || '—' }}</TableCell><TableCell>{{ price(position.initialStop) }}</TableCell>
                  <TableCell>{{ price(position.trailingStop) }}</TableCell><TableCell>{{ price(position.nextAddPrice) }}</TableCell>
                  <TableCell>{{ price(position.exitLevel) }}</TableCell><TableCell>{{ score(position.alphaScore) }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
            <template #horizontal-scrollbar>
              <ScrollBar orientation="horizontal" />
            </template>
          </ScrollArea>
        </template>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>策略生命周期</CardTitle>
        <CardDescription>CANDIDATE、ENTRY、ADD、HOLD、REDUCE 与 EXIT 都会保留在观察区。</CardDescription>
      </CardHeader>
      <CardContent>
        <Empty v-if="!loading && !candidates.length">
          <EmptyHeader><EmptyTitle>暂无策略候选</EmptyTitle><EmptyDescription>所选交易日没有处于策略生命周期的股票。</EmptyDescription></EmptyHeader>
        </Empty>
        <div
          v-else
          class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
        >
          <button
            v-for="item in candidates"
            :key="item.code"
            class="rounded-md border p-3 text-left hover:bg-muted/50"
            data-testid="trend-candidate"
            @click="openDetail(item)"
          >
            <div class="flex items-center justify-between gap-2">
              <strong class="truncate">#{{ item.rank }} {{ item.name }}</strong>
              <Badge :variant="badgeVariant(item.action)">
                {{ actionText(item.action) }}
              </Badge>
            </div>
            <p class="mt-1 font-mono text-xs text-muted-foreground">
              {{ item.code }}
            </p>
            <div class="mt-3 flex items-center justify-between text-sm">
              <span class="flex items-center gap-1"><IndicatorLabel
                label="Alpha"
                :description="descriptions.alpha"
              /> {{ score(item.alphaScore) }}</span>
              <Badge :variant="badgeVariant(item.state)">
                {{ stateText(item.state) }}
              </Badge>
            </div>
          </button>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>Today's Changes</CardTitle>
        <CardDescription>相对 {{ changes?.previousTradeDate || '上一可用交易日' }} 的市场、状态和显著分数变化。</CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="grid gap-3 sm:grid-cols-2">
          <div
            class="rounded border p-3"
            data-testid="trend-market-score-change"
          >
            <IndicatorLabel
              label="Market Score Δ"
              :description="descriptions.marketScoreChange"
            />
            <strong class="mt-1 block text-lg">{{ scoreDelta(changes?.marketScoreChange) }}</strong>
          </div>
          <div
            class="rounded border p-3"
            data-testid="trend-breadth-score-change"
          >
            <IndicatorLabel
              label="Breadth Score Δ"
              :description="descriptions.breadthScoreChange"
            />
            <strong class="mt-1 block text-lg">{{ scoreDelta(changes?.breadthScoreChange) }}</strong>
          </div>
        </div>
        <div
          class="max-h-[32rem] space-y-4 overflow-y-auto pr-2"
          data-testid="trend-changes-scroll"
          tabindex="0"
          aria-label="Today's Changes 明细"
        >
          <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <section
              v-for="group in changeGroups"
              :key="group.label"
              class="rounded border p-3"
            >
              <h3 class="mb-2 flex items-center justify-between text-sm font-semibold">
                {{ group.label }} <Badge :variant="group.variant">
                  {{ group.items.length }}
                </Badge>
              </h3>
              <button
                v-for="change in group.items"
                :key="change.current.code"
                class="mb-2 block w-full rounded bg-muted/50 p-2 text-left text-xs hover:bg-muted"
                :data-testid="`trend-change-${group.label.toLowerCase().replace(' ', '-')}`"
                @click="openDetail(change.current)"
              >
                <strong>{{ change.current.name }}</strong>
                <span class="ml-1 font-mono text-muted-foreground">{{ change.current.code }}</span>
                <span class="mt-1 block">{{ transitionText(change) }} · Alpha Δ {{ scoreDelta(change.alphaScoreChange) }}</span>
              </button>
              <p
                v-if="!group.items.length"
                class="text-xs text-muted-foreground"
              >
                无
              </p>
            </section>
          </div>
          <section>
            <h3 class="mb-2 text-sm font-semibold">
              State Transitions
            </h3>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="change in changes?.transitions ?? []"
                :key="change.current.code"
                data-testid="trend-transition"
                class="rounded border px-3 py-2 text-left text-xs hover:bg-muted/50"
                @click="openDetail(change.current)"
              >
                <strong>{{ change.current.name }}</strong>
                <span class="ml-2">{{ transitionText(change) }}</span>
                <span class="ml-2">{{ change.previousAction ?? '—' }} → {{ change.current.action }}</span>
              </button>
              <span
                v-if="!changes?.transitions?.length"
                class="text-xs text-muted-foreground"
              >无状态转换</span>
            </div>
          </section>
          <section>
            <h3 class="mb-2 text-sm font-semibold">
              Rank / Score Movers
            </h3>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="change in changes?.movers ?? []"
                :key="change.current.code"
                data-testid="trend-mover"
                class="rounded border px-3 py-2 text-left text-xs hover:bg-muted/50"
                @click="openDetail(change.current)"
              >
                <strong>{{ change.current.name }}</strong>
                <span class="ml-2">Rank {{ rankDelta(change.rankChange) }}</span>
                <span class="ml-2">Trend {{ scoreDelta(change.trendScoreChange) }}</span>
                <span class="ml-2">RS {{ scoreDelta(change.rsScoreChange) }}</span>
                <span class="ml-2">Alpha {{ scoreDelta(change.alphaScoreChange) }}</span>
              </button>
              <span
                v-if="!changes?.movers?.length"
                class="text-xs text-muted-foreground"
              >无显著变化</span>
            </div>
          </section>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="flex-row flex-wrap items-center justify-between gap-3">
        <div><CardTitle>趋势排名</CardTitle><CardDescription>{{ summary.tradeDate || '—' }} · {{ scope }} · {{ summary.dataReadyCount }}/{{ summary.universeSize }} 数据就绪</CardDescription></div>
        <NativeSelect
          v-model="sortKey"
          size="sm"
          aria-label="排序"
        >
          <NativeSelectOption value="rank">
            Rank
          </NativeSelectOption>
          <NativeSelectOption value="alphaScore">
            Alpha Score
          </NativeSelectOption>
          <NativeSelectOption value="trendScore">
            Trend Score
          </NativeSelectOption>
          <NativeSelectOption value="rsScore">
            RS Score
          </NativeSelectOption>
          <NativeSelectOption value="breakoutScore">
            Breakout Score
          </NativeSelectOption>
        </NativeSelect>
      </CardHeader>
      <CardContent class="px-0">
        <Empty v-if="!loading && !items.length">
          <EmptyHeader><EmptyTitle>暂无趋势快照</EmptyTitle><EmptyDescription>请确认所选日期已完成收盘行情同步和策略计算。</EmptyDescription></EmptyHeader>
        </Empty>
        <ScrollArea
          v-else
          class="w-full"
        >
          <Table class="min-w-[2450px]">
            <TableHeader>
              <TableRow>
                <TableHead>
                  <IndicatorLabel
                    label="Rank"
                    :description="descriptions.rank"
                  />
                </TableHead><TableHead>股票</TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="State"
                    :description="descriptions.state"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Action"
                    :description="descriptions.action"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Alpha"
                    :description="descriptions.alpha"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Trend"
                    :description="descriptions.trend"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="RS"
                    :description="descriptions.relativeStrength"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Breakout"
                    :description="descriptions.breakout"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Setup"
                    :description="descriptions.setup"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="5D Return"
                    :description="descriptions.return"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="10D Return"
                    :description="descriptions.return"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="20D Return"
                    :description="descriptions.return"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="ATR"
                    :description="descriptions.atr"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Reference"
                    :description="descriptions.reference"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Signal Date"
                    :description="descriptions.signal"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Signal Price"
                    :description="descriptions.signal"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Entry Date"
                    :description="descriptions.entry"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Entry Price"
                    :description="descriptions.entry"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Stop"
                    :description="descriptions.initialStop"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Next Add"
                    :description="descriptions.nextAdd"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Exit Level"
                    :description="descriptions.exitLevel"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="理论初始权重"
                    :description="descriptions.initialWeight"
                  />
                </TableHead>
                <TableHead class="w-[480px] min-w-[420px]">
                  <IndicatorLabel
                    label="Reasons"
                    :description="descriptions.reasons"
                  />
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="item in sortedItems"
                :key="item.code"
                class="cursor-pointer"
                data-testid="trend-row"
                @click="openDetail(item)"
              >
                <TableCell>#{{ item.rank }}</TableCell><TableCell><strong class="block">{{ item.name }}</strong><span class="font-mono text-xs text-muted-foreground">{{ item.code }}</span></TableCell>
                <TableCell>
                  <Badge :variant="badgeVariant(item.state)">
                    {{ stateText(item.state) }}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge :variant="badgeVariant(item.action)">
                    {{ actionText(item.action) }}
                  </Badge>
                </TableCell>
                <TableCell class="font-bold text-primary">
                  {{ score(item.alphaScore) }}
                </TableCell><TableCell>{{ score(item.trendScore) }}</TableCell>
                <TableCell>{{ score(item.rsScore) }}</TableCell><TableCell>{{ score(item.breakoutScore) }}</TableCell><TableCell>{{ item.setup }}</TableCell>
                <TableCell>{{ pct(item.features.return5D) }}</TableCell><TableCell>{{ pct(item.features.return10D) }}</TableCell><TableCell>{{ pct(item.features.return20D) }}</TableCell><TableCell>{{ price(item.atr) }}</TableCell>
                <TableCell>{{ price(item.referencePrice) }}</TableCell>
                <TableCell>{{ item.signalDate || '—' }}</TableCell><TableCell>{{ price(item.signalPrice) }}</TableCell>
                <TableCell>{{ item.openedAt || '—' }}</TableCell><TableCell>{{ price(item.entryPrice) }}</TableCell>
                <TableCell>{{ price(item.initialStop) }}</TableCell>
                <TableCell>{{ price(item.nextAddPrice) }}</TableCell><TableCell>{{ price(item.exitLevel) }}</TableCell><TableCell>{{ pct(item.suggestedInitialWeight) }}</TableCell>
                <TableCell class="w-[480px] min-w-[420px] max-w-[520px]">
                  <TooltipProvider :delay-duration="150">
                    <Tooltip>
                      <TooltipTrigger as-child>
                        <div
                          class="truncate whitespace-nowrap"
                          data-testid="trend-reasons"
                          tabindex="0"
                        >
                          {{ item.reasons.join('；') || '—' }}
                        </div>
                      </TooltipTrigger>
                      <TooltipContent class="max-w-sm whitespace-normal">
                        {{ item.reasons.join('；') || '—' }}
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
          <template #horizontal-scrollbar>
            <ScrollBar orientation="horizontal" />
          </template>
        </ScrollArea>
      </CardContent>
    </Card>

    <Sheet
      :open="detailOpen"
      @update:open="value => { detailOpen = value; }"
    >
      <SheetContent
        class="w-full overflow-y-auto sm:max-w-2xl"
        data-testid="trend-detail"
      >
        <SheetHeader><SheetTitle>{{ detail?.metadata.name || '趋势详情' }}</SheetTitle><SheetDescription>{{ detail?.metadata.code }} · 指标、风险线与 point-in-time 状态历史</SheetDescription></SheetHeader>
        <div
          v-if="detailLoading"
          class="space-y-3 px-4"
        >
          <Skeleton
            v-for="index in 6"
            :key="index"
            class="h-16"
          />
        </div>
        <AppApiErrorAlert
          v-else-if="detailError"
          class="mx-4"
          :error="detailError"
        />
        <div
          v-else-if="detail"
          class="space-y-5 px-4 pb-6"
        >
          <div class="flex flex-wrap gap-2">
            <Badge :variant="badgeVariant(detail.latest.state)">
              {{ stateText(detail.latest.state) }}
            </Badge><Badge :variant="badgeVariant(detail.latest.action)">
              {{ actionText(detail.latest.action) }}
            </Badge><Badge variant="outline">
              {{ detail.latest.setup }}
            </Badge>
          </div>
          <section>
            <h3 class="mb-2 font-semibold">
              <IndicatorLabel
                label="Alpha Score Breakdown"
                :description="descriptions.alpha"
              />
            </h3><pre class="overflow-x-auto rounded bg-muted p-3 text-xs">{{ JSON.stringify(detail.latest.scoreBreakdown, null, 2) }}</pre>
          </section>
          <section>
            <h3 class="mb-2 font-semibold">
              Trend / RS / Breakout
            </h3><div class="grid grid-cols-2 gap-2 text-sm">
              <div>
                <IndicatorLabel
                  label="Weighted slope 15D"
                  :description="descriptions.weightedSlope"
                  wrap
                /><strong class="block">{{ score(detail.latest.features.rawWeightedSlope) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="Slope percentile 15D"
                  :description="descriptions.slopePercentile"
                  wrap
                /><strong class="block">{{ score(detail.latest.features.weightedSlopePercentile) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="R²"
                  :description="descriptions.r2"
                  wrap
                /><strong class="block">{{ score(detail.latest.features.weightedR2) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="Return 5D / 10D / 20D"
                  :description="descriptions.return"
                  wrap
                /><strong class="block">{{ pct(detail.latest.features.return5D) }} / {{ pct(detail.latest.features.return10D) }} / {{ pct(detail.latest.features.return20D) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="Drawdown 20D"
                  :description="descriptions.drawdown"
                  wrap
                /><strong class="block">{{ pct(detail.latest.features.drawdown20D) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="MA10 / MA20"
                  :description="descriptions.movingAverage"
                  wrap
                /><strong class="block">{{ score(detail.latest.features.ma10) }} / {{ score(detail.latest.features.ma20) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="RS 5D / 10D / 20D"
                  :description="descriptions.rawRelativeStrength"
                  wrap
                /><strong class="block">{{ pct(detail.latest.features.rs5D) }} / {{ pct(detail.latest.features.rs10D) }} / {{ pct(detail.latest.features.rs20D) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="Return Percentile 10D / 20D"
                  :description="descriptions.returnPercentile"
                  wrap
                /><strong class="block">{{ score(detail.latest.features.return10DPercentile) }} / {{ score(detail.latest.features.return20DPercentile) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="10D / 20D Breakout"
                  :description="descriptions.breakoutFlags"
                  wrap
                /><strong class="block">{{ detail.latest.features.breakout10D ? '是' : '否' }} / {{ detail.latest.features.breakout20D ? '是' : '否' }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="Trend Resume"
                  :description="descriptions.trendResume"
                  wrap
                /><strong class="block">{{ detail.latest.features.trendResume ? '是' : '否' }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="Volume / Compression"
                  :description="descriptions.volumeCompression"
                  wrap
                /><strong class="block">{{ score(detail.latest.features.volumeRatio) }} / {{ detail.latest.features.priorCompression ? '是' : '否' }}</strong>
              </div>
            </div>
          </section>
          <section>
            <h3 class="mb-2 font-semibold">
              Risk（理论策略 NAV）
            </h3><div class="grid grid-cols-2 gap-2 text-sm">
              <div>
                <IndicatorLabel
                  label="ATR"
                  :description="descriptions.atr"
                  wrap
                /><strong class="block">{{ price(detail.latest.atr) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="Units"
                  :description="descriptions.units"
                  wrap
                /><strong class="block">{{ detail.latest.units }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="Signal Date / Price"
                  :description="descriptions.signal"
                  wrap
                /><strong class="block">{{ detail.latest.signalDate || '—' }} / {{ price(detail.latest.signalPrice) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="Entry Date / Price"
                  :description="descriptions.entry"
                  wrap
                /><strong class="block">{{ detail.latest.openedAt || '—' }} / {{ price(detail.latest.entryPrice) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="Stop"
                  :description="descriptions.initialStop"
                  wrap
                /><strong class="block">{{ price(detail.latest.initialStop) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="Trailing / Exit"
                  :description="`${descriptions.trailingStop} ${descriptions.exitLevel}`"
                  wrap
                /><strong class="block">{{ price(detail.latest.trailingStop) }} / {{ price(detail.latest.exitLevel) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="Next Add"
                  :description="descriptions.nextAdd"
                  wrap
                /><strong class="block">{{ price(detail.latest.nextAddPrice) }}</strong>
              </div>
              <div>
                <IndicatorLabel
                  label="理论风险权重"
                  :description="descriptions.initialWeight"
                  wrap
                /><strong class="block">{{ pct(detail.latest.suggestedInitialWeight) }}</strong>
              </div>
            </div>
          </section>
          <section>
            <h3 class="mb-2 font-semibold">
              历史 Snapshot / 状态变化
            </h3><div class="space-y-2">
              <div
                v-for="snapshot in detail.history"
                :key="snapshot.tradeDate"
                class="flex flex-wrap items-center justify-between gap-2 rounded border p-2 text-sm"
                data-testid="trend-history"
              >
                <span>{{ snapshot.tradeDate }}</span><span>Alpha {{ score(snapshot.alphaScore) }}</span><Badge :variant="badgeVariant(snapshot.state)">
                  {{ stateText(snapshot.state) }}
                </Badge><Badge :variant="badgeVariant(snapshot.action)">
                  {{ actionText(snapshot.action) }}
                </Badge>
              </div>
            </div>
          </section>
        </div>
      </SheetContent>
    </Sheet>
  </div>
</template>
