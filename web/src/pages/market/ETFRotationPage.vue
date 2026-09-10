<script setup lang="ts">
import { useRoute } from 'vue-router';
import { etfRotationApi } from '@/api/etfRotation';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import IndicatorLabel from '@/components/app/IndicatorHelpLabel.vue';
import LoadingButton from '@/components/app/LoadingButton.vue';
import ResearchDataModeToggle from '@/components/research/ResearchDataModeToggle.vue';
import ResearchDataStatusBar from '@/components/research/ResearchDataStatusBar.vue';
import ETFRotationHistoryCharts from '@/components/etf-rotation/ETFRotationHistoryCharts.vue';
import { indicatorDescriptions as descriptions } from '@/components/etf-rotation/indicatorDescriptions';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type {
  ETFAction,
  ETFChange,
  ETFDetailResponse,
  ETFMarket,
  ETFMarketRotationSnapshot,
  ETFMomentumSnapshot,
  ETFPreviewResponse,
  ETFRankingChanges,
  ETFRankingResponse,
  ETFState,
} from '@/types/etfRotation';
import { formatMarketCurrencyAmount } from '@/utils/marketCurrency';
import {
  chooseDefaultResearchDataMode,
  diffPreviewActionChanges,
  isPreviewCompleted,
  type ResearchDataMode,
} from '@/utils/researchPreview';
import { RefreshCcw } from 'lucide-vue-next';
import { computed, onMounted, ref, watch } from 'vue';
import { toast } from 'vue-sonner';

const items = ref<ETFMomentumSnapshot[]>([]);
const candidates = ref<ETFMomentumSnapshot[]>([]);
const exits = ref<ETFMomentumSnapshot[]>([]);
const changes = ref<ETFRankingChanges | null>(null);
const marketSnapshot = ref<ETFMarketRotationSnapshot | null>(null);
const summary = ref({ tradeDate: '', universeSize: 0, dataReadyCount: 0, dataCoverage: 0,
  rankableSize: 0, rankableCoverage: 0, generatedAt: null as string | null, warnings: [] as string[] });
const selectedDate = ref('');
const availableDates = ref<string[]>([]);
const loading = ref(true);
const refreshing = ref(false);
const runLoading = ref(false);
const error = ref<ParsedApiError | null>(null);
const selected = ref<ETFDetailResponse | null>(null);
const detailLoading = ref(false);
const detailError = ref<ParsedApiError | null>(null);
const route = useRoute();
const market = ref<ETFMarket>(route?.query.market === 'US' ? 'US' : 'CN');
const sortKey = ref<'compositeScore' | 'momentumStrengthScore' | 'trendQualityScore' | 'relativeStrengthScore' | 'entryScore'>('compositeScore');
const dataMode = ref<ResearchDataMode>('official');
const modeChosenByUser = ref(false);
const preview = ref<ETFPreviewResponse | null>(null);
const officialLatest = ref<ETFRankingResponse | null>(null);
let generation = 0;

const previewAvailable = computed(() => preview.value != null);
const showingPreview = computed(() => dataMode.value === 'preview' && isPreviewCompleted(preview.value?.status));
const showingStrategyBody = computed(() => dataMode.value === 'official' || showingPreview.value);
const sortedItems = computed(() => [...items.value].sort((a, b) => {
  const left = a[sortKey.value] ?? -Infinity;
  const right = b[sortKey.value] ?? -Infinity;
  return right - left || a.code.localeCompare(b.code);
}));
const changeGroups = computed(() => [
  { label: 'NEW BUY', items: changes.value?.newBuys ?? [], variant: 'success' as const, transition: 'action' as const },
  { label: 'NEW EXIT', items: changes.value?.newExits ?? [], variant: 'destructive' as const, transition: 'action' as const },
  { label: 'NEW EMERGING', items: changes.value?.newEmerging ?? [], variant: 'info' as const, transition: 'state' as const },
  { label: 'NEW COOLING', items: changes.value?.newCooling ?? [], variant: 'warning' as const, transition: 'state' as const },
]);
const previewChangeGroups = computed(() => {
  const diff = diffPreviewActionChanges(items.value, officialLatest.value?.items ?? []);
  return [
    { label: 'NEW BUY', items: diff.newBuys, variant: 'success' as const },
    { label: 'NEW EXIT', items: diff.newExits, variant: 'destructive' as const },
    { label: 'NEW EMERGING', items: diff.newEmerging, variant: 'info' as const },
    { label: 'NEW COOLING', items: diff.newCooling, variant: 'warning' as const },
  ];
});
const previewHasChanges = computed(() => previewChangeGroups.value.some(group => group.items.length));
function pct(value: number | null | undefined, sign = true) { return value == null ? '—' : `${sign && value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`; }
function stopPct(value: number | null | undefined) { return value == null ? '—' : `-${(value * 100).toFixed(1)}%`; }
function score(value: number | null | undefined) { return value == null ? '—' : value.toFixed(1); }
function decimal(value: number | null | undefined, digits = 3) { return value == null ? '—' : value.toFixed(digits); }
function price(value: number | null) { return formatMarketCurrencyAmount(value, market.value); }
function rankChange(value: number | null) { return value == null ? '—' : `${value > 0 ? '+' : ''}${value}`; }
function scoreChange(value: number | null) { return value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(1)}`; }
function boolText(value: boolean | null) { return value == null ? '—' : value ? '通过' : '未通过'; }
function stateIcon(state: ETFState) { return ({ EMERGING: '🚀', STRONG: '🟢', TRENDING: '🔵', COOLING: '🟡', EXHAUSTED: '🔴', WEAK: '⚫', NEUTRAL: '⚪' })[state]; }
function stateVariant(state: ETFState): 'default' | 'success' | 'warning' | 'destructive' | 'info' | 'outline' {
  if (state === 'STRONG' || state === 'EMERGING') return 'destructive';
  if (state === 'TRENDING') return 'default';
  if (state === 'COOLING' || state === 'EXHAUSTED') return 'warning';
  return state === 'WEAK' ? 'outline' : 'info';
}
function actionVariant(action: ETFAction | null): 'default' | 'success' | 'warning' | 'destructive' | 'info' | 'outline' {
  if (action === 'BUY') return 'success'; if (action === 'HOLD') return 'default';
  if (action === 'EXIT') return 'destructive'; return 'outline';
}
function correlationText(item: ETFMomentumSnapshot) {
  const value = item.diagnostics?.correlation as { status?: string; max_with_universe?: number | null } | undefined;
  if (!value || value.status !== 'ready' || value.max_with_universe == null) return '相关性数据不足';
  return `最高相关性 ${(value.max_with_universe * 100).toFixed(0)}%`;
}
function changeTransition(change: ETFChange, transition: 'action' | 'state') {
  if (transition === 'action') return `${change.previousAction ?? 'NEW'} → ${change.current.action}`;
  return `${change.previousState ?? 'NEW'} → ${change.current.state}`;
}
function vsOfficial(item: ETFMomentumSnapshot) {
  if (!showingPreview.value) return null;
  const baseline = officialLatest.value?.items.find(row => row.code === item.code);
  if (!baseline) return null;
  const scoreDelta = item.compositeScore != null && baseline.compositeScore != null
    ? item.compositeScore - baseline.compositeScore
    : null;
  const rankDelta = item.rank != null && baseline.rank != null ? baseline.rank - item.rank : null;
  return { scoreDelta, rankDelta, previousRank: baseline.rank };
}
function applyPreviewPayload(payload: ETFPreviewResponse | null) {
  if (!payload) {
    items.value = [];
    candidates.value = [];
    exits.value = [];
    changes.value = null;
    marketSnapshot.value = null;
    return;
  }
  summary.value = {
    tradeDate: payload.tradeDate,
    universeSize: payload.universeSize,
    dataReadyCount: payload.dataReadyCount ?? 0,
    dataCoverage: payload.dataCoverage,
    rankableSize: payload.rankableCount ?? payload.items.length,
    rankableCoverage: payload.rankableCoverage ?? 0,
    generatedAt: payload.previewTime,
    warnings: payload.warnings ?? [],
  };
  if (!isPreviewCompleted(payload.status)) {
    items.value = [];
    candidates.value = [];
    exits.value = [];
    changes.value = null;
    marketSnapshot.value = null;
    return;
  }
  items.value = payload.items;
  marketSnapshot.value = payload.marketSnapshot;
  candidates.value = payload.items.filter(item => item.isCandidate);
  exits.value = payload.items.filter(item => item.action === 'EXIT');
  changes.value = null;
}
async function applyOfficialRanking(current: number, requestedMarket: ETFMarket, latest: ETFRankingResponse) {
  const requestedDate = selectedDate.value;
  const ranking = requestedDate && requestedDate !== latest.tradeDate
    ? await etfRotationApi.ranking(requestedMarket, requestedDate)
    : latest;
  if (current !== generation) return;
  Object.assign(summary.value, ranking);
  marketSnapshot.value = ranking.marketSnapshot;
  items.value = ranking.items;
  changes.value = ranking.changes ?? null;
  if (!selectedDate.value) selectedDate.value = ranking.tradeDate;
  const result = await etfRotationApi.candidates(requestedMarket, ranking.tradeDate);
  if (current !== generation) return;
  candidates.value = result.candidates ?? result.items.filter(item => item.action === 'BUY' || item.action === 'HOLD');
  exits.value = result.exits ?? result.items.filter(item => item.action === 'EXIT');
}
async function load(refreshDates = false, options: { autoSelectMode?: boolean } = {}) {
  const current = ++generation;
  const autoSelectMode = options.autoSelectMode === true;
  if (loading.value && !refreshing.value) loading.value = true;
  else refreshing.value = true;
  error.value = null;
  try {
    const requestedMarket = market.value;
    const [dates, latestOfficial, previewPayload] = await Promise.all([
      refreshDates || !availableDates.value.length ? etfRotationApi.dates(requestedMarket) : Promise.resolve(null),
      etfRotationApi.ranking(requestedMarket, undefined),
      etfRotationApi.preview(requestedMarket),
    ]);
    if (current !== generation) return;
    if (dates) availableDates.value = dates.items;
    officialLatest.value = latestOfficial;
    preview.value = previewPayload;
    if (autoSelectMode) {
      dataMode.value = chooseDefaultResearchDataMode({
        officialTradeDate: latestOfficial.tradeDate,
        officialGeneratedAt: latestOfficial.generatedAt,
        previewAvailable: previewPayload != null,
        previewStatus: previewPayload?.status,
        previewTradeDate: previewPayload?.tradeDate,
        previewTime: previewPayload?.previewTime,
      });
    }
    if (dataMode.value === 'preview') applyPreviewPayload(previewPayload);
    else await applyOfficialRanking(current, requestedMarket, latestOfficial);
  } catch (err) {
    if (current === generation) {
      error.value = getParsedApiError(err);
      items.value = [];
      candidates.value = [];
      exits.value = [];
      changes.value = null;
    }
  } finally {
    if (current === generation) {
      loading.value = false;
      refreshing.value = false;
    }
  }
}
function selectDataMode(mode: ResearchDataMode) {
  if (mode === dataMode.value) return;
  if (mode === 'preview' && !previewAvailable.value) return;
  modeChosenByUser.value = true;
  dataMode.value = mode;
  if (mode === 'preview') {
    applyPreviewPayload(preview.value);
    return;
  }
  void load(false, { autoSelectMode: false });
}
async function openDetail(item: ETFMomentumSnapshot) {
  selected.value = { market: market.value, metadata: item, latest: item, history: [], marketSnapshot: marketSnapshot.value };
  detailLoading.value = true; detailError.value = null;
  try { selected.value = await etfRotationApi.detail(item.code, market.value); }
  catch (err) { detailError.value = getParsedApiError(err); } finally { detailLoading.value = false; }
}
async function runRotation() { runLoading.value = true; try { const result = await etfRotationApi.run(market.value); toast.success(`任务已提交：${result.taskId}`); }
  catch (err) { error.value = getParsedApiError(err); } finally { runLoading.value = false; } }
watch(market, () => {
  selectedDate.value = '';
  availableDates.value = [];
  selected.value = null;
  modeChosenByUser.value = false;
  void load(true, { autoSelectMode: true });
});
onMounted(() => void load(true, { autoSelectMode: true }));
</script>

<template>
  <div class="min-w-0 space-y-4">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold">
          ETF 动量轮动 · Fast Rotation
        </h2><p class="mt-1 text-xs text-muted-foreground">
          完全基于公开市场行情的多维轮动看板；Action 是公共策略信号，不代表个人交易建议。
        </p>
      </div>
      <div class="flex flex-wrap items-end gap-2">
        <NativeSelect
          v-model="market"
          class="h-10"
          aria-label="市场"
        >
          <NativeSelectOption value="CN">
            A股
          </NativeSelectOption><NativeSelectOption value="US">
            美股
          </NativeSelectOption>
        </NativeSelect>
        <ResearchDataModeToggle
          :mode="dataMode"
          :preview-available="previewAvailable"
          preview-hint="暂无预演"
          @update:mode="selectDataMode"
        />
        <AppDatePicker
          v-if="dataMode === 'official'"
          :model-value="selectedDate"
          label="交易日"
          :available-dates="availableDates"
          :clearable="false"
          :disabled="loading || refreshing"
          class="w-56"
          data-testid="etf-rotation-date"
          @update:model-value="value => { selectedDate = value; load(false, { autoSelectMode: false }); }"
        />
        <p
          v-else
          class="flex h-10 items-center text-sm text-muted-foreground"
          data-testid="etf-rotation-date-readonly"
        >
          今日 · {{ summary.tradeDate || '—' }}
        </p>
        <span
          data-testid="etf-rotation-trade-date"
          class="sr-only"
        >{{ summary.tradeDate }}</span>
        <Button
          variant="outline"
          class="h-10"
          data-testid="etf-rotation-refresh"
          :disabled="loading || refreshing"
          @click="load(true, { autoSelectMode: false })"
        >
          <RefreshCcw class="size-4" />刷新
        </Button>
        <LoadingButton
          class="h-10"
          data-testid="etf-rotation-run"
          :loading="runLoading"
          loading-text="提交中…"
          @click="runRotation"
        >
          手动运行
        </LoadingButton>
      </div>
    </header>
    <ResearchDataStatusBar
      :mode="dataMode"
      :trade-date="summary.tradeDate"
      :data-as-of="preview?.dataAsOf"
      :preview-time="preview?.previewTime"
      :generated-at="dataMode === 'official' ? summary.generatedAt : preview?.previewTime"
      :provider="preview?.provider"
      :official-trade-date="officialLatest?.tradeDate"
      :preview-status="preview?.status"
      :reason="preview?.warnings?.join('；') || null"
    />
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <div
      v-if="summary.warnings.length && showingStrategyBody"
      class="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200"
      role="alert"
    >
      {{ summary.warnings.join('；') }}
    </div>
    <div
      v-if="loading"
      class="grid gap-3 sm:grid-cols-4"
    >
      <Skeleton
        v-for="i in 4"
        :key="i"
        class="h-24"
      />
    </div>
    <div
      v-else
      class="relative space-y-4"
      :class="refreshing ? 'opacity-70' : ''"
    >
    <Card v-if="showingStrategyBody">
      <CardHeader>
        <CardTitle class="flex items-center gap-2">
          <IndicatorLabel
            label="Market Regime"
            :description="descriptions.regime"
          /><Badge :variant="marketSnapshot?.regime === 'RISK_ON' ? 'success' : marketSnapshot?.regime === 'RISK_OFF' ? 'destructive' : 'warning'">
            {{ marketSnapshot?.regime ?? 'N/A' }}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div class="rounded border p-3">
          <IndicatorLabel
            label="Positive 5D Breadth"
            :description="descriptions.breadth"
          /><strong class="mt-1 block">{{ pct(marketSnapshot?.positive5dBreadth, false) }}</strong>
        </div>
        <div class="rounded border p-3">
          <IndicatorLabel
            label="Breadth > MA10"
            :description="descriptions.breadth"
          /><strong class="mt-1 block">{{ pct(marketSnapshot?.aboveMa10Breadth, false) }}</strong>
        </div>
        <div class="rounded border p-3">
          <IndicatorLabel
            label="Benchmark"
            :description="descriptions.benchmark"
          /><strong class="mt-1 block break-words">{{ marketSnapshot?.benchmarkCode ?? '—' }}</strong>
        </div>
        <div class="rounded border p-3">
          <IndicatorLabel
            label="Benchmark Trend"
            :description="descriptions.benchmarkTrend"
          /><strong class="mt-1 block">{{ marketSnapshot?.benchmarkTrend ?? '—' }}</strong>
        </div>
      </CardContent>
    </Card>

    <Card v-if="showingStrategyBody">
      <CardHeader><CardTitle>Current Candidates</CardTitle><CardDescription>当前 BUY / HOLD 候选；采用 Top4 Entry、Top6 Hold、risk group 和 20 日相关性约束。</CardDescription></CardHeader>
      <CardContent>
        <p
          v-if="!loading && !candidates.length"
          class="text-sm text-muted-foreground"
        >
          暂无当前候选
        </p>
        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <button
            v-for="item in candidates"
            :key="item.code"
            data-testid="rotation-candidate"
            class="min-w-0 rounded border p-3 text-left hover:bg-muted/50"
            @click="openDetail(item)"
          >
            <div class="flex items-center justify-between gap-2">
              <strong class="min-w-0 break-words">#{{ item.candidateRank ?? '—' }} {{ item.name }}</strong><Badge :variant="actionVariant(item.action)">
                {{ item.action ?? '—' }}
              </Badge>
            </div>
            <p class="mt-1 truncate text-xs text-muted-foreground">
              {{ item.code }} · {{ item.riskGroup }}
            </p>
            <div class="mt-3 flex justify-between text-sm">
              <span>Composite {{ score(item.compositeScore) }}</span><Badge :variant="stateVariant(item.state)">
                {{ stateIcon(item.state) }} {{ item.state }}
              </Badge>
            </div>
            <div
              v-if="vsOfficial(item)"
              class="mt-2 space-y-1 text-xs text-amber-700 dark:text-amber-300"
              data-testid="rotation-candidate-vs-official"
            >
              <p v-if="vsOfficial(item)?.scoreDelta != null">
                {{ vsOfficial(item)!.scoreDelta! >= 0 ? '↑' : '↓' }} {{ scoreChange(vsOfficial(item)!.scoreDelta) }} vs 正式
              </p>
              <p v-if="vsOfficial(item)?.rankDelta != null">
                Rank #{{ item.rank ?? '—' }}
                <span v-if="vsOfficial(item)!.rankDelta"> {{ vsOfficial(item)!.rankDelta! > 0 ? '↑' : '↓' }} {{ Math.abs(vsOfficial(item)!.rankDelta!) }}</span>
              </p>
            </div>
            <div class="mt-2 text-xs">
              趋势 {{ boolText(item.absoluteTrendEligible) }} · 流动性 {{ boolText(item.liquidityEligible) }}
            </div><div class="mt-1 break-words text-xs">
              {{ correlationText(item) }} · Stop {{ stopPct(item.stopLossPct) }} · {{ price(item.suggestedStopPrice) }}
            </div>
          </button>
        </div>
      </CardContent>
    </Card>

        <Card
      v-if="showingPreview"
      data-testid="etf-preview-changes"
    >
      <CardHeader>
        <CardTitle>Preview Changes</CardTitle>
        <CardDescription>相对上次正式收盘结果的对比，不参与当前 Preview 状态计算。</CardDescription>
      </CardHeader>
      <CardContent>
        <p
          v-if="!previewHasChanges"
          class="text-sm text-muted-foreground"
        >
          暂无相对上次正式收盘的新变化
        </p>
        <div
          v-else
          class="grid gap-3 md:grid-cols-2 xl:grid-cols-4"
        >
          <section
            v-for="group in previewChangeGroups"
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
              :data-testid="`etf-preview-change-${group.label.toLowerCase().replace(' ', '-')}`"
              @click="openDetail(change.current)"
            >
              <strong>{{ change.current.name }}</strong>
              <span class="ml-1 font-mono text-muted-foreground">{{ change.current.code }}</span>
            </button>
          </section>
        </div>
      </CardContent>
    </Card>

<Card v-if="showingStrategyBody">
      <CardHeader><CardTitle>Today's Exit</CardTitle><CardDescription>所选交易日 action = EXIT 的全部标的；此分区不受候选数量 limit 限制。</CardDescription></CardHeader>
      <CardContent>
        <p
          v-if="!loading && !exits.length"
          class="text-sm text-muted-foreground"
        >
          今日无退出信号
        </p>
        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <button
            v-for="item in exits"
            :key="item.code"
            data-testid="rotation-exit"
            class="min-w-0 rounded border border-destructive/30 p-3 text-left hover:bg-muted/50"
            @click="openDetail(item)"
          >
            <div class="flex items-center justify-between gap-2">
              <strong class="min-w-0 break-words">{{ item.name }}</strong>
              <Badge variant="destructive">
                EXIT
              </Badge>
            </div>
            <p class="mt-1 truncate font-mono text-xs text-muted-foreground">
              {{ item.code }}
            </p>
            <div class="mt-3 flex justify-between text-sm">
              <span>Composite {{ score(item.compositeScore) }}</span>
              <Badge :variant="stateVariant(item.state)">
                {{ stateIcon(item.state) }} {{ item.state }}
              </Badge>
            </div>
          </button>
        </div>
      </CardContent>
    </Card>

    <Card v-if="dataMode === 'official' && showingStrategyBody">
      <CardHeader>
        <CardTitle>Today's Changes</CardTitle>
        <CardDescription>相对 {{ changes?.previousTradeDate || '上一可用交易日' }} 的信号、状态和排名变化。</CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div
          v-if="changes?.regimeChange"
          class="rounded border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/30"
          data-testid="etf-regime-change"
        >
          <strong>Regime Change</strong>
          <span class="ml-2">{{ changes.regimeChange.from }} → {{ changes.regimeChange.to }}</span>
        </div>
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
            <div class="space-y-2">
              <button
                v-for="change in group.items"
                :key="change.current.code"
                class="block w-full rounded bg-muted/50 p-2 text-left text-xs hover:bg-muted"
                :data-testid="`etf-change-${group.label.toLowerCase().replace(' ', '-')}`"
                @click="openDetail(change.current)"
              >
                <strong>{{ change.current.name }}</strong>
                <span class="ml-1 font-mono text-muted-foreground">{{ change.current.code }}</span>
                <span class="mt-1 block">{{ changeTransition(change, group.transition) }} · Composite Δ {{ scoreChange(change.compositeScoreChange) }}</span>
              </button>
              <p
                v-if="!group.items.length"
                class="text-xs text-muted-foreground"
              >
                无
              </p>
            </div>
          </section>
        </div>
        <section>
          <h3 class="mb-2 text-sm font-semibold">
            Rank Movers
          </h3>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="change in changes?.rankMovers ?? []"
              :key="change.current.code"
              data-testid="etf-rank-mover"
              class="rounded border px-3 py-2 text-left text-xs hover:bg-muted/50"
              @click="openDetail(change.current)"
            >
              <strong>{{ change.current.name }}</strong>
              <span class="ml-2">#{{ change.previousRank ?? '—' }} → #{{ change.current.rank ?? '—' }} ({{ rankChange(change.rankChange) }})</span>
              <span class="ml-2">Composite Δ {{ scoreChange(change.compositeScoreChange) }}</span>
            </button>
            <span
              v-if="!changes?.rankMovers?.length"
              class="text-xs text-muted-foreground"
            >无显著排名变化</span>
          </div>
        </section>
      </CardContent>
    </Card>

    <Card v-if="showingStrategyBody">
      <CardHeader class="flex-row flex-wrap items-center justify-between gap-3">
        <div><CardTitle>Rotation Ranking</CardTitle><CardDescription>比较核心得分、状态和 5D / 20D 收益；点击 ETF 查看完整指标。</CardDescription></div>
        <NativeSelect
          v-model="sortKey"
          size="sm"
        >
          <NativeSelectOption value="compositeScore">
            Composite
          </NativeSelectOption><NativeSelectOption value="momentumStrengthScore">
            Momentum
          </NativeSelectOption><NativeSelectOption value="trendQualityScore">
            Trend Quality
          </NativeSelectOption><NativeSelectOption value="relativeStrengthScore">
            Relative Strength
          </NativeSelectOption><NativeSelectOption value="entryScore">
            Entry
          </NativeSelectOption>
        </NativeSelect>
      </CardHeader>
      <CardContent class="px-0">
        <ScrollArea class="w-full">
          <Table class="w-full">
            <TableHeader>
              <TableRow>
                <TableHead>Rank</TableHead>
                <TableHead>ETF</TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Composite"
                    :description="descriptions.composite"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Momentum"
                    :description="descriptions.momentum"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Trend Quality"
                    :description="descriptions.trendQuality"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Relative Strength"
                    :description="descriptions.relativeStrength"
                  />
                </TableHead>
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
                <TableHead
                  v-for="window in [5,20]"
                  :key="window"
                >
                  <IndicatorLabel
                    :label="`${window}D`"
                    :description="descriptions.return"
                  />
                </TableHead>
                <TableHead>
                  <IndicatorLabel
                    label="Rank Δ 1/3/5D"
                    :description="descriptions.rankChange"
                  />
                </TableHead>
              </TableRow>
            </TableHeader><TableBody>
              <TableRow
                v-for="item in sortedItems"
                :key="item.code"
                class="cursor-pointer"
                @click="openDetail(item)"
              >
                <TableCell>#{{ item.rank ?? '—' }}</TableCell>
                <TableCell class="max-w-44">
                  <strong class="block break-words">{{ item.name }}</strong><span class="font-mono text-xs text-muted-foreground">{{ item.code }}</span>
                </TableCell>
                <TableCell class="font-bold text-primary">
                  {{ score(item.compositeScore) }}
                </TableCell>
                <TableCell>{{ score(item.momentumStrengthScore) }}</TableCell>
                <TableCell>{{ score(item.trendQualityScore) }}</TableCell>
                <TableCell>{{ score(item.relativeStrengthScore) }}</TableCell>
                <TableCell>
                  <Badge :variant="stateVariant(item.state)">
                    {{ stateIcon(item.state) }} {{ item.state }}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge :variant="actionVariant(item.action)">
                    {{ item.action ?? '—' }}
                  </Badge>
                </TableCell>
                <TableCell
                  v-for="key in (['ret5D','ret20D'] as const)"
                  :key="key"
                >
                  {{ pct(item[key]) }}
                </TableCell>
                <TableCell>{{ rankChange(item.rankChange1D) }} / {{ rankChange(item.rankChange3D) }} / {{ rankChange(item.rankChange5D) }}</TableCell>
              </TableRow>
            </TableBody>
          </Table><template #horizontal-scrollbar>
            <ScrollBar orientation="horizontal" />
          </template>
        </ScrollArea>
      </CardContent>
    </Card>
    </div>

    <Dialog
      :open="selected !== null"
      @update:open="open => { if (!open) selected = null; }"
    >
      <DialogContent
        data-testid="etf-detail-modal"
        class="flex max-h-[calc(100dvh-2rem)] w-[calc(100%-1rem)] max-w-[calc(100%-1rem)] flex-col overflow-hidden p-0 sm:max-w-[calc(100%-2rem)] lg:max-w-6xl"
      >
        <DialogHeader class="border-b p-5 text-left">
          <DialogTitle class="break-words">
            {{ selected?.metadata.name }} · {{ selected?.metadata.code }}
          </DialogTitle><DialogDescription>{{ selected?.metadata.category }} / {{ selected?.metadata.theme }} · {{ selected?.metadata.riskGroup }}</DialogDescription>
        </DialogHeader>
        <div class="min-h-0 flex-1 space-y-5 overflow-y-auto overflow-x-hidden p-5">
          <AppApiErrorAlert
            v-if="detailError"
            :error="detailError"
          /><Skeleton
            v-if="detailLoading"
            class="h-48"
          />
          <template v-else-if="selected">
            <div
              data-testid="etf-factor-grid"
              class="grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-3"
            >
              <div
                v-for="factor in ([['Entry',selected.latest.entryScore,descriptions.entry],['Composite',selected.latest.compositeScore,descriptions.composite],['Momentum',selected.latest.momentumStrengthScore,descriptions.momentum],['Relative Strength',selected.latest.relativeStrengthScore,descriptions.relativeStrength],['Acceleration',selected.latest.accelerationScore,descriptions.acceleration],['Trend Quality',selected.latest.trendQualityScore,descriptions.trendQuality],['Efficiency',selected.latest.efficiencyScore,descriptions.efficiency]] as const)"
                :key="factor[0]"
                class="min-w-0 rounded border p-3"
              >
                <IndicatorLabel
                  :label="factor[0]"
                  :description="factor[2]"
                  wrap
                /><strong class="mt-1 block text-xl">{{ score(factor[1]) }}</strong>
              </div>
            </div>
            <Card>
              <CardHeader><CardTitle>Raw Metrics</CardTitle></CardHeader><CardContent
                data-testid="etf-raw-metrics-grid"
                class="grid grid-cols-[repeat(auto-fit,minmax(11rem,1fr))] gap-2"
              >
                <div
                  v-for="metric in ([['1D',pct(selected.latest.ret1D),descriptions.return],['3D',pct(selected.latest.ret3D),descriptions.return],['5D',pct(selected.latest.ret5D),descriptions.return],['10D',pct(selected.latest.ret10D),descriptions.return],['20D',pct(selected.latest.ret20D),descriptions.return],['RS5',pct(selected.latest.rs5D),descriptions.relativeStrength],['RS10',pct(selected.latest.rs10D),descriptions.relativeStrength],['RS20',pct(selected.latest.rs20D),descriptions.relativeStrength],['Weighted Slope 5D',decimal(selected.latest.weightedSlope5D,5),descriptions.weightedSlope],['Weighted Slope 10D',decimal(selected.latest.weightedSlope10D,5),descriptions.weightedSlope],['Weighted Slope 15D',decimal(selected.latest.weightedSlope15D,5),descriptions.weightedSlope],['Annualized Slope 5D',pct(selected.latest.annualizedSlope5D),descriptions.weightedSlope],['Annualized Slope 10D',pct(selected.latest.annualizedSlope10D),descriptions.weightedSlope],['Annualized Slope 15D',pct(selected.latest.annualizedSlope15D),descriptions.weightedSlope],['R² 15D',decimal(selected.latest.trendR215D),descriptions.r2],['Trend Quality 15D',decimal(selected.latest.trendQuality15D),descriptions.trendQuality],['Momentum Acceleration 3D',pct(selected.latest.momentumAcceleration3D),descriptions.acceleration],['Momentum Acceleration 5D',pct(selected.latest.momentumAcceleration5D),descriptions.acceleration],['Trend Acceleration',pct(selected.latest.trendAcceleration),descriptions.acceleration],['Signed ER10',decimal(selected.latest.signedEfficiencyRatio10D),descriptions.efficiency],['Volatility 20D',pct(selected.latest.realizedVol20D,false),descriptions.volatility],['Max Drawdown 20D',pct(selected.latest.maxDrawdown20D),descriptions.drawdown],['MA10 Deviation',pct(selected.latest.ma10Ratio),descriptions.maDeviation],['MA20 Deviation',pct(selected.latest.ma20Ratio),descriptions.maDeviation],['Distance from High',pct(selected.latest.distanceFrom20dHigh),descriptions.distanceHigh],['Volume Ratio',decimal(selected.latest.volumeRatio5D),descriptions.volumeRatio],['Average Amount',price(selected.latest.avgAmount20D),descriptions.liquidity],['Rank Change 1/3/5D',`${rankChange(selected.latest.rankChange1D)} / ${rankChange(selected.latest.rankChange3D)} / ${rankChange(selected.latest.rankChange5D)}`,descriptions.rankChange],['Suggested Stop',price(selected.latest.suggestedStopPrice),descriptions.stop]] as const)"
                  :key="metric[0]"
                  class="min-w-0 rounded border px-3 py-2"
                >
                  <IndicatorLabel
                    :label="metric[0]"
                    :description="metric[2] || metric[0]"
                    wrap
                  /><strong class="mt-1 block tabular-nums [overflow-wrap:anywhere]">{{ metric[1] }}</strong>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Eligibility & Signal</CardTitle></CardHeader><CardContent class="grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-3">
                <div>
                  <IndicatorLabel
                    label="Absolute Trend"
                    :description="descriptions.absoluteTrend"
                    wrap
                  /><strong class="block">{{ boolText(selected.latest.absoluteTrendEligible) }}</strong>
                </div>
                <div>
                  <IndicatorLabel
                    label="Liquidity"
                    :description="descriptions.liquidity"
                    wrap
                  /><strong class="block">{{ boolText(selected.latest.liquidityEligible) }}</strong>
                </div>
                <div>
                  <IndicatorLabel
                    label="State"
                    :description="descriptions.state"
                    wrap
                  /><strong class="block">{{ selected.latest.state }}</strong>
                </div>
                <div>
                  <IndicatorLabel
                    label="Action"
                    :description="descriptions.action"
                    wrap
                  /><strong class="block">{{ selected.latest.action ?? '—' }}</strong>
                </div>
              </CardContent>
            </Card>
            <Card><CardHeader><CardTitle>History</CardTitle><CardDescription>价格/MA、Composite、Rank 与 Relative Strength；旧快照缺失字段时保留空点。</CardDescription></CardHeader><CardContent><ETFRotationHistoryCharts :history="selected.history" /></CardContent></Card>
          </template>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>
