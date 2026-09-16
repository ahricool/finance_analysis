<script setup lang="ts">
import { detailChartHistory as buildDetailChartHistory } from '@/utils/detailChartHistory';
import ResearchMarketToggle from '@/components/research/ResearchMarketToggle.vue';
import { useRoute } from 'vue-router';
import { useLazyResearchPreview } from '@/composables/useLazyResearchPreview';
import { computed, onMounted, ref, shallowRef, watch } from 'vue';
import { RefreshCcw } from 'lucide-vue-next';
import { toast } from 'vue-sonner';
import { trendFollowingApi } from '@/api/trendFollowing';
import { createParsedApiError, getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import IndicatorLabel from '@/components/app/IndicatorHelpLabel.vue';
import LoadingButton from '@/components/app/LoadingButton.vue';
import ResearchDataModeToggle from '@/components/research/ResearchDataModeToggle.vue';
import ResearchDataStatusBar from '@/components/research/ResearchDataStatusBar.vue';
import { trendIndicatorDescriptions as descriptions } from '@/components/trend-following/indicatorDescriptions';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import TrendFragilityHistoryChart from '@/components/trend-following/TrendFragilityHistoryChart.vue';
import TrendMarketOverview from '@/components/trend-following/TrendMarketOverview.vue';
import TrendRankHistoryChart from '@/components/trend-following/TrendRankHistoryChart.vue';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
import type {
  TrendAlphaBreakdown,
  TrendDetailResponse,
  TrendMarket,
  TrendPreviewResponse,
  TrendPreviewStatusResponse,
  TrendRankingChanges,
  TrendRankingResponse,
  TrendSnapshot,
  TrendRankingSnapshot,
  TrendState,
  TrendSummary,
} from '@/types/trendFollowing';
import { formatMarketCurrencyAmount } from '@/utils/marketCurrency';
import {
  asRankingSnapshot,
  rankingFeatureValue,
} from '@/utils/rankingFeatures';
import type { RankingFeatureKey } from '@/types/trendFollowing';
import { RANKING_FEATURE_KEYS } from '@/types/trendFollowing';
import {
  chooseDefaultResearchDataMode,
  isPreviewCompleted,
  type ResearchDataMode,
} from '@/utils/researchPreview';

const emptySummary = (): TrendSummary => ({
  market: 'CN', tradeDate: '', universeKey: 'cn_csi300_csi500', benchmarkCode: '510300.SH',
  marketRegime: 'NEUTRAL', marketScore: 0, universeSize: 0,
  dataReadyCount: 0, dataCoverage: 0, rankableCount: 0, candidateCount: 0,
  warnings: [], features: {},
  scoreBreakdown: {}, generatedAt: '',
});
const route = useRoute();
const market = ref<TrendMarket>(route?.query.market === 'US' ? 'US' : 'CN');
const selectedDate = ref('');
const availableDates = ref<string[]>([]);
const summary = ref<TrendSummary>(emptySummary());
const items = shallowRef<TrendRankingSnapshot[]>([]);
const changes = ref<TrendRankingChanges | null>(null);
const loading = ref(true);
const refreshing = ref(false);
const running = ref(false);
const error = ref<ParsedApiError | null>(null);
const dataMode = ref<ResearchDataMode>('official');
const modeChosenByUser = ref(false);
const { previewStatus, previewPayload, previewLoading, previewError, refreshPreviewStatus, loadPreview, resetPreview } =
  useLazyResearchPreview<TrendMarket, TrendPreviewStatusResponse, TrendPreviewResponse>(() => market.value, trendFollowingApi);
const previewInfo = computed(() => previewPayload.value ?? previewStatus.value);
const officialLatest = shallowRef<TrendRankingResponse | null>(null);
const officialSelected = shallowRef<TrendRankingResponse | null>(null);
const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref<TrendDetailResponse | null>(null);
const detailError = ref<ParsedApiError | null>(null);
const alphaContributions = computed(() => {
  const alpha = detail.value?.latest.scoreBreakdown.alpha as TrendAlphaBreakdown | undefined;
  if (alpha?.version !== 2) return [];
  return ['trend', 'rs', 'setup', 'path'].map(key => ({
    key, value: alpha.components[key], weight: alpha.weights[key], contribution: alpha.contributions[key],
  }));
});

const historyLoading = ref(false);
const historyError = ref<ParsedApiError | null>(null);
let detailRequestId = 0;
const detailChartHistory = computed(() => detail.value
  ? buildDetailChartHistory(detail.value.history, detail.value.latest, detailMode.value === 'preview')
  : []);
const rankingColumns = [
  { key: 'rank', label: 'Alpha Rank', group: 'Core', format: 'number', description: descriptions.rank },
  { key: 'name', label: '股票名称', group: 'Core', format: 'text', description: undefined },
  { key: 'state', label: 'State', group: 'Core', format: 'text', description: descriptions.state },
  { key: 'trendLifecycle', label: 'Lifecycle / Age', group: 'Core', format: 'number', description: '趋势阶段与持续交易日数。MATURE 表示趋势成熟阶段。' },
  { key: 'rankChange5D', label: '排名趋势', group: 'Core', format: 'number', description: descriptions.rankChange },
  { key: 'referencePrice', label: 'Reference Price', group: 'Core', format: 'price', description: descriptions.reference },
  { key: 'alphaScore', label: 'Alpha Score', group: 'Alpha', format: 'score', description: descriptions.alpha },
  { key: 'alphaTrendContribution', label: 'Trend Contribution', group: 'Alpha', format: 'score', description: descriptions.alpha },
  { key: 'alphaRsContribution', label: 'RS Contribution', group: 'Alpha', format: 'score', description: descriptions.alpha },
  { key: 'alphaSetupContribution', label: 'Setup Contribution', group: 'Alpha', format: 'score', description: descriptions.alpha },
  { key: 'alphaPathContribution', label: 'Path Contribution', group: 'Alpha', format: 'score', description: descriptions.alpha },
  { key: 'trendScore', label: 'Trend Score', group: 'Trend', format: 'score', description: descriptions.trend },
  { key: 'weightedSlopePercentile', label: 'Slope Percentile 15D', group: 'Trend', format: 'score', description: descriptions.slopePercentile },
  { key: 'r2Quality', label: 'R² Quality', group: 'Trend', format: 'score', description: descriptions.r2Quality },
  { key: 'momentumQuality', label: 'Momentum Quality', group: 'Trend', format: 'score', description: descriptions.momentumQuality },
  { key: 'return10DQuality', label: 'Return 10D Quality', group: 'Trend', format: 'score', description: descriptions.returnQuality },
  { key: 'return20DQuality', label: 'Return 20D Quality', group: 'Trend', format: 'score', description: descriptions.returnQuality },
  { key: 'drawdownQuality', label: 'Drawdown Quality', group: 'Trend', format: 'score', description: descriptions.drawdownQuality },
  { key: 'rsScore', label: 'RS Score', group: 'RS', format: 'score', description: descriptions.relativeStrength },
  { key: 'rs5DQuality', label: 'RS 5D Quality', group: 'RS', format: 'score', description: descriptions.rsQuality },
  { key: 'rs10DQuality', label: 'RS 10D Quality', group: 'RS', format: 'score', description: descriptions.rsQuality },
  { key: 'rs20DQuality', label: 'RS 20D Quality', group: 'RS', format: 'score', description: descriptions.rsQuality },
  { key: 'setupScore', label: 'Setup Score', group: 'Setup', format: 'score', description: descriptions.breakout },
  { key: 'breakoutQuality', label: 'Breakout Quality', group: 'Setup', format: 'score', description: descriptions.breakout },
  { key: 'extensionQuality', label: 'Extension Quality', group: 'Setup', format: 'score', description: descriptions.breakout },
  { key: 'volumeQuality', label: 'Volume Quality', group: 'Setup', format: 'score', description: descriptions.breakout },
  { key: 'compressionQuality', label: 'Compression Quality', group: 'Setup', format: 'score', description: descriptions.breakout },
  { key: 'pathScore', label: 'Path Score', group: 'Path', format: 'score', description: descriptions.path },
  { key: 'concentrationQuality', label: 'Concentration Quality', group: 'Path', format: 'score', description: descriptions.concentration },
  { key: 'volatilityQuality', label: 'Volatility Quality', group: 'Path', format: 'score', description: descriptions.expansion },
  { key: 'downsideControlQuality', label: 'Downside Control Quality', group: 'Path', format: 'score', description: descriptions.downside },
  { key: 'setup', label: 'Setup', group: 'Signals / Explain', format: 'text', description: descriptions.setup },
  { key: 'trendCandidate', label: 'Trend Candidate', group: 'Signals / Explain', format: 'boolean', description: descriptions.candidate },
  { key: 'priorCompression', label: 'Prior Compression', group: 'Signals / Explain', format: 'boolean', description: descriptions.volumeCompression },
  { key: 'compressionBreakout', label: 'Compression Breakout', group: 'Signals / Explain', format: 'boolean', description: descriptions.setup },
  { key: 'trendResume', label: 'Trend Resume', group: 'Signals / Explain', format: 'boolean', description: descriptions.trendResume },
  { key: 'signedEfficiencyRatio10D', label: 'Signed Efficiency 10D', group: 'Signals / Explain', format: 'score', description: descriptions.path },
  { key: 'rawWeightedSlope', label: 'Weighted Slope 15D', group: 'Signals / Explain', format: 'slope', description: descriptions.weightedSlope },
  { key: 'weightedR2', label: 'Weighted R²', group: 'Signals / Explain', format: 'r2', description: descriptions.r2 },
  { key: 'return5D', label: '5D Return', group: 'Signals / Explain', format: 'percent', description: descriptions.return },
  { key: 'return10D', label: '10D Return', group: 'Signals / Explain', format: 'percent', description: descriptions.return },
  { key: 'return20D', label: '20D Return', group: 'Signals / Explain', format: 'percent', description: descriptions.return },
  { key: 'drawdown20D', label: 'Drawdown 20D', group: 'Signals / Explain', format: 'percent', description: descriptions.drawdown },
  { key: 'rs5D', label: 'RS 5D', group: 'Signals / Explain', format: 'percent', description: descriptions.rawRelativeStrength },
  { key: 'rs10D', label: 'RS 10D', group: 'Signals / Explain', format: 'percent', description: descriptions.rawRelativeStrength },
  { key: 'rs20D', label: 'RS 20D', group: 'Signals / Explain', format: 'percent', description: descriptions.rawRelativeStrength },
  { key: 'volumeRatio', label: 'Volume Ratio', group: 'Signals / Explain', format: 'score', description: descriptions.volumeCompression },
  { key: 'positiveReturnConcentration', label: 'Return Concentration', group: 'Signals / Explain', format: 'percent', description: descriptions.concentration },
  { key: 'atrExpansionRatio', label: 'ATR Expansion', group: 'Signals / Explain', format: 'ratio', description: descriptions.expansion },
  { key: 'downsideUpsideRatio', label: 'Downside / Upside', group: 'Signals / Explain', format: 'ratio', description: descriptions.downside },
  { key: 'ma10', label: 'MA10', group: 'Signals / Explain', format: 'score', description: descriptions.movingAverage },
  { key: 'ma20', label: 'MA20', group: 'Signals / Explain', format: 'score', description: descriptions.movingAverage },
  { key: 'ma10Slope', label: 'MA10 Slope', group: 'Signals / Explain', format: 'percent', description: descriptions.movingAverage },
  { key: 'ma20Slope', label: 'MA20 Slope', group: 'Signals / Explain', format: 'percent', description: descriptions.movingAverage },
  { key: 'distanceFromMa20', label: 'Distance From MA20', group: 'Signals / Explain', format: 'percent', description: descriptions.movingAverage },
  { key: 'fragilityScore', label: 'Fragility', group: 'Risk / Health', format: 'score', description: '0–100；越高表示内部恶化越快。历史不足显示 —，并不代表稳定。' },
  { key: 'atr', label: 'ATR', group: 'Risk / Health', format: 'score', description: descriptions.atr },
  { key: 'trendQuality', label: 'Trend Quality', group: 'Risk / Health', format: 'score', description: undefined },
  { key: 'trendAcceleration', label: 'Trend Acceleration', group: 'Risk / Health', format: 'score', description: undefined },
] as const;
const rankingGroups = [...new Set(rankingColumns.map(column => column.group))].map(label => ({
  label, count: rankingColumns.filter(column => column.group === label).length,
}));
type SortKey = typeof rankingColumns[number]['key'];
type StateFilter = 'all' | 'CANDIDATE' | 'TRENDING' | 'WEAKENING' | 'BROKEN';
const rankingSearch = ref('');
const stateFilter = ref<StateFilter>('all');
const stateFilters: Array<{ value: StateFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'CANDIDATE', label: '趋势候选' },
  { value: 'TRENDING', label: '趋势健康' },
  { value: 'WEAKENING', label: '趋势弱化' },
  { value: 'BROKEN', label: '趋势破坏' },
];
const sortKey = ref<SortKey>('rank');
const sortDirection = ref<'asc' | 'desc'>('asc');
let generation = 0;
const marketOverviewRefreshKey = ref(0);
const marketOverviewReady = ref(false);
const detailMode = ref<ResearchDataMode>('official');

const scope = computed(() => market.value === 'CN' ? '沪深300 + 中证500' : 'S&P 500');
const ITEM_SORT_KEYS = ['rank', 'name', 'state', 'setup', 'alphaScore', 'trendScore', 'rsScore', 'breakoutScore',
  'referencePrice', 'atr', 'fragilityScore'] as const;
function isItemSortKey(key: SortKey): key is typeof ITEM_SORT_KEYS[number] {
  return ITEM_SORT_KEYS.some(item => item === key);
}
function isRankingFeatureKey(key: SortKey): key is RankingFeatureKey {
  return RANKING_FEATURE_KEYS.some(item => item === key);
}
function sortValue(item: TrendRankingSnapshot, key: SortKey): string | number | boolean | null {
  if (key === 'trendLifecycle') return item.trendDurationDays;
  if (key === 'rankChange5D') return item.rankChange5D ?? item.rankChange3D ?? item.rankChange1D;
  if (isItemSortKey(key)) {
    const raw = item[key];
    if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
    if (typeof raw === 'string' || typeof raw === 'boolean') return raw;
    return null;
  }
  return isRankingFeatureKey(key) ? rankingFeatureValue(item, key) : null;
}
function rankingCell(item: TrendRankingSnapshot, column: typeof rankingColumns[number]) {
  const value = sortValue(item, column.key);
  if (value == null) return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'string') return value;
  if (column.format === 'percent') return pct(value);
  if (column.format === 'price') return price(value);
  if (column.format === 'r2') return value.toFixed(3);
  if (column.format === 'slope') return value.toFixed(4);
  if (column.format === 'ratio') return value.toFixed(2);
  if (column.format === 'score' || column.format === 'number') return score(value);
  return String(value);
}
function toggleSort(key: SortKey) {
  sortDirection.value = sortKey.value === key
    ? (sortDirection.value === 'asc' ? 'desc' : 'asc')
    : (['rank', 'name', 'setup', 'state', 'trendCandidate', 'priorCompression', 'compressionBreakout', 'trendResume'].includes(key) ? 'asc' : 'desc');
  sortKey.value = key;
}
const filteredItems = computed(() => {
  const query = rankingSearch.value.trim().toLocaleLowerCase();
  return items.value.filter(item => {
    if (stateFilter.value !== 'all' && item.state !== stateFilter.value) return false;
    return !query || item.code.toLocaleLowerCase().includes(query) || item.name.toLocaleLowerCase().includes(query);
  });
});
const sortedItems = computed(() => [...filteredItems.value].sort((left, right) => {
  const a = sortValue(left, sortKey.value);
  const b = sortValue(right, sortKey.value);
  if (a == null) return b == null ? 0 : 1;
  if (b == null) return -1;
  const comparison = typeof a !== 'string' && typeof b !== 'string' ? Number(a) - Number(b) : String(a).localeCompare(String(b));
  return comparison * (sortDirection.value === 'asc' ? 1 : -1) || left.code.localeCompare(right.code);
}));
// Production CN currently has ~3,800 rows. Keep one sortable dataset, but only
// mount the scroll viewport plus overscan; this is not business pagination.
const rankingViewport = ref<HTMLElement | null>(null);
const rankingScrollTop = ref(0);
const virtualRanking = computed(() => sortedItems.value.length > 300);
const rankingRowHeight = 64;
const virtualStart = computed(() => virtualRanking.value
  ? Math.min(Math.max(0, sortedItems.value.length - 28), Math.max(0, Math.floor((rankingScrollTop.value - 80) / rankingRowHeight) - 8)) : 0);
const renderedRankingRows = computed(() => virtualRanking.value
  ? sortedItems.value.slice(virtualStart.value, virtualStart.value + 28) : sortedItems.value);
const rankingBottomSpace = computed(() => virtualRanking.value
  ? Math.max(0, sortedItems.value.length - virtualStart.value - renderedRankingRows.value.length) * rankingRowHeight : 0);
watch(sortedItems, () => {
  rankingScrollTop.value = 0;
  if (rankingViewport.value) rankingViewport.value.scrollTop = 0;
});
const cards = computed(() => [
  ['Market Regime', summary.value.marketRegime, descriptions.marketRegime],
  ['Market Score', score(summary.value.marketScore), descriptions.marketScore],
  ['Universe Size', summary.value.universeSize, descriptions.universeSize],
  ['Data Coverage', pct(summary.value.dataCoverage), descriptions.dataCoverage],
  ['Rankable', summary.value.rankableCount, descriptions.rankable],
  ['Candidate', summary.value.candidateCount, descriptions.candidate],
]);
const previewAvailable = computed(() => previewStatus.value != null);
const showingPreview = computed(() => dataMode.value === 'preview' && !previewLoading.value && isPreviewCompleted(previewPayload.value?.status));
const showingStrategyBody = computed(() => dataMode.value === 'official' || showingPreview.value);

function score(value: number | null | undefined) { return value == null ? '—' : value.toFixed(1); }
function scoreDelta(value: number | null | undefined) { return value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(1)}`; }
function rankDelta(value: number | null | undefined) { return value == null ? '—' : `${value > 0 ? '+' : ''}${value}`; }
function pct(value: number | null | undefined) { return value == null ? '—' : `${(value * 100).toFixed(1)}%`; }
function price(value: number | null | undefined) {
  return value == null ? '—' : formatMarketCurrencyAmount(value, market.value);
}
function stateText(state: TrendState) {
  return ({ IDLE: '无明显趋势', WATCHING: '趋势形成', CANDIDATE: '趋势候选', TRENDING: '趋势健康',
    WEAKENING: '趋势弱化', BROKEN: '趋势破坏' })[state];
}
function badgeVariant(value: string): 'default' | 'success' | 'warning' | 'destructive' | 'info' | 'outline' {
  if (['TRENDING', 'RISK_ON'].includes(value)) return 'success';
  if (['BROKEN', 'RISK_OFF'].includes(value)) return 'destructive';
  if (['WEAKENING', 'NEUTRAL'].includes(value)) return 'warning';
  if (value === 'CANDIDATE') return 'info';
  return 'outline';
}
function applyPreviewPayload(payload: TrendPreviewResponse | null) {
  if (!payload) {
    items.value = [];
    changes.value = null;
    return;
  }
  summary.value = {
    ...emptySummary(),
    market: payload.market,
    tradeDate: payload.tradeDate,
    universeKey: payload.universeKey,
    benchmarkCode: payload.benchmarkCode,
    marketRegime: payload.marketRegime,
    marketScore: payload.marketScore,
    universeSize: payload.universeSize,
    dataReadyCount: payload.dataReadyCount,
    dataCoverage: payload.dataCoverage,
    rankableCount: payload.rankableCount,
    candidateCount: payload.candidateCount,
    warnings: payload.warnings ?? [],
    features: payload.features ?? {},
    scoreBreakdown: payload.scoreBreakdown ?? {},
    generatedAt: payload.previewTime ?? '',
  };
  if (!isPreviewCompleted(payload.status)) {
    items.value = [];
    changes.value = null;
    return;
  }
  items.value = payload.snapshots.map(asRankingSnapshot);
  changes.value = null;
}
function applyOfficialRanking(ranking: TrendRankingResponse) {
  summary.value = ranking;
  items.value = ranking.items;
  changes.value = ranking.changes ?? null;
  selectedDate.value = ranking.tradeDate;
}
async function showPreview() {
  const current = generation;
  const requestedMarket = market.value;
  await loadPreview();
  if (current === generation && requestedMarket === market.value && dataMode.value === 'preview') {
    applyPreviewPayload(previewPayload.value);
  }
}
async function load(refreshDates = false, options: { autoSelectMode?: boolean } = {}) {
  const current = ++generation;
  // Mount history only after the anchor date and automatic data mode have settled.
  marketOverviewReady.value = false;
  if (refreshDates) marketOverviewRefreshKey.value++;
  const requestedMarket = market.value;
  const requestedDate = selectedDate.value || undefined;
  const autoSelectMode = options.autoSelectMode === true;
  refreshing.value = !loading.value;
  error.value = null;
  const auxiliary = refreshDates || !availableDates.value.length;
  const refreshVisiblePreview = refreshDates && dataMode.value === 'preview';
  // Auxiliaries update independently; a slow/failed preview must not block official data.
  if (auxiliary) void trendFollowingApi.dates(requestedMarket).then(result => {
    if (current === generation) availableDates.value = result.items;
  }).catch(() => undefined);
  const previewTask = auxiliary ? refreshPreviewStatus(refreshVisiblePreview) : Promise.resolve();
  try {
    const ranking = await trendFollowingApi.ranking(requestedMarket, requestedDate);
    if (current !== generation) return;
    officialSelected.value = ranking;
    if (!requestedDate || requestedDate === availableDates.value[0]) officialLatest.value = ranking;
    selectedDate.value = ranking.tradeDate;
    if (dataMode.value === 'official') applyOfficialRanking(ranking);
    loading.value = false;
    refreshing.value = false;
    await previewTask;
    if (current !== generation) return;
    if (autoSelectMode && !modeChosenByUser.value) {
      dataMode.value = chooseDefaultResearchDataMode({
        officialTradeDate: ranking.tradeDate,
        officialGeneratedAt: ranking.generatedAt,
        previewAvailable: previewStatus.value != null,
        previewStatus: previewStatus.value?.status,
        previewTradeDate: previewStatus.value?.tradeDate,
        previewTime: previewStatus.value?.previewTime,
      });
    }
    if (dataMode.value === 'preview') await showPreview();
    else applyOfficialRanking(ranking);
  } catch (reason) {
    if (current === generation) {
      error.value = getParsedApiError(reason);
      items.value = [];
      changes.value = null;
      officialSelected.value = null;
    }
  } finally {
    if (current === generation) {
      marketOverviewReady.value = true;
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
    void showPreview();
    return;
  }
  if (officialSelected.value) applyOfficialRanking(officialSelected.value);
  else void load(false, { autoSelectMode: false });
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
async function loadDetailHistory() {
  const current = detail.value;
  if (!current || detailMode.value !== 'preview') return;
  const requestId = ++detailRequestId;
  historyLoading.value = true;
  historyError.value = null;
  try {
    const response = await trendFollowingApi.detailHistory(current.latest.code, current.market, current.latest.tradeDate);
    if (requestId === detailRequestId && detail.value === current) {
      current.history = response.history.filter(row => row.tradeDate < current.latest.tradeDate);
    }
  } catch (reason) {
    if (requestId === detailRequestId && detail.value === current) historyError.value = getParsedApiError(reason);
  } finally {
    if (requestId === detailRequestId) historyLoading.value = false;
  }
}
async function openDetail(item: Pick<TrendSnapshot, 'code'> & { tradeDate?: string; preview?: boolean }) {
  const requestId = ++detailRequestId;
  historyLoading.value = false;
  historyError.value = null;
  detailMode.value = item.preview === undefined ? dataMode.value : item.preview ? 'preview' : 'official';
  detailOpen.value = true;
  detailError.value = null;
  detailLoading.value = true;
  detail.value = null;
  if (detailMode.value === 'preview') {
    if (item.preview === true && !previewPayload.value) await loadPreview();
    if (requestId !== detailRequestId) return;
    const snapshot = previewPayload.value?.snapshots.find(row => row.code === item.code);
    if (!snapshot) {
      detailError.value = previewError.value ?? createParsedApiError({
        title: 'Preview 详情不可用',
        message: `当前 Preview 中未找到 ${item.code}，请刷新后重试。`,
      });
      detailLoading.value = false;
      return;
    }
    detail.value = {
      market: market.value,
      metadata: { market: market.value, code: snapshot.code, name: snapshot.name },
      latest: snapshot,
      history: [],
      marketContext: summary.value,
    };
    detailLoading.value = false;
    void loadDetailHistory();
    return;
  }
  try {
    const response = await trendFollowingApi.detail(
      item.code,
      market.value,
      60,
      item.preview === undefined ? selectedDate.value || item.tradeDate : item.tradeDate,
    );
    if (requestId === detailRequestId) detail.value = response;
  } catch (reason) {
    if (requestId === detailRequestId) detailError.value = getParsedApiError(reason);
  } finally {
    if (requestId === detailRequestId) detailLoading.value = false;
  }
}
watch(market, () => {
  ++detailRequestId;
  selectedDate.value = '';
  rankingSearch.value = '';
  stateFilter.value = 'all';
  officialSelected.value = null;
  officialLatest.value = null;
  resetPreview();
  items.value = [];
  changes.value = null;
  availableDates.value = [];
  detailOpen.value = false;
  summary.value = { ...emptySummary(), market: market.value };
  modeChosenByUser.value = false;
  void load(true, { autoSelectMode: true });
});
function setMarket(target: TrendMarket) {
  if (market.value === target) return;
  market.value = target;
}
onMounted(() => void load(true, { autoSelectMode: true }));
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
          {{ scope }} · 股票趋势状态与风险指标。
        </p>
      </div>
      <div class="flex flex-wrap items-end gap-2">
        <ResearchMarketToggle
          :model-value="market"
          data-testid="trend-market"
          @update:model-value="setMarket"
        />
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
          data-testid="trend-date"
          @update:model-value="value => { selectedDate = value; load(false, { autoSelectMode: false }); }"
        />
        <p
          v-else
          class="flex h-10 items-center text-sm text-muted-foreground"
          data-testid="trend-date-readonly"
        >
          今日 · {{ previewInfo?.tradeDate || '—' }}
        </p>
        <Button
          variant="outline"
          class="h-10"
          data-testid="trend-refresh"
          :disabled="loading || refreshing"
          @click="load(true, { autoSelectMode: false })"
        >
          <RefreshCcw class="size-4" />刷新
        </Button>
        <LoadingButton
          v-if="dataMode === 'official'"
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
    <ResearchDataStatusBar
      :mode="dataMode"
      :trade-date="dataMode === 'preview' ? previewInfo?.tradeDate : summary.tradeDate"
      :data-as-of="previewInfo?.dataAsOf"
      :preview-time="previewInfo?.previewTime"
      :generated-at="dataMode === 'official' ? summary.generatedAt : previewInfo?.previewTime"
      :provider="previewInfo?.provider"
      :official-trade-date="officialLatest?.tradeDate"
      :preview-status="previewInfo?.status"
      :reason="previewInfo?.warnings?.join('；') || null"
    />
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <AppApiErrorAlert
      v-if="dataMode === 'preview' && previewError"
      :error="previewError"
    />
    <p
      v-if="dataMode === 'preview' && previewLoading"
      role="status"
      class="text-sm text-muted-foreground"
    >
      正在加载盘中预演…
    </p>
    <div
      v-if="summary.warnings.length && showingStrategyBody"
      role="alert"
      class="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200"
    >
      {{ summary.warnings.join('；') }}
    </div>
    <div
      v-if="loading || (dataMode === 'preview' && previewLoading)"
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
      class="relative space-y-4"
      :class="refreshing ? 'opacity-70' : ''"
    >
      <div
        v-if="showingStrategyBody"
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



      <TrendMarketOverview
        v-if="!loading && marketOverviewReady"
        :market="market"
        :as-of="dataMode === 'official' ? selectedDate || undefined : undefined"
        :include-preview="dataMode === 'preview'"
        :refresh-key="marketOverviewRefreshKey"
        @select="openDetail"
      />

      <Card v-if="dataMode === 'official' && showingStrategyBody">
        <CardHeader>
          <CardTitle>市场与分数变化</CardTitle>
          <CardDescription>相对 {{ changes?.previousTradeDate || '上一可用交易日' }} 的市场和显著分数变化。</CardDescription>
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
            aria-label="市场与分数变化 明细"
          >
            <section>
              <h3 class="mb-2 text-sm font-semibold">
                Rank / Score Movers
              </h3>
              <div class="flex flex-wrap gap-2">
                <button
                  v-for="change in changes?.movers ?? []"
                  :key="change.code"
                  data-testid="trend-mover"
                  class="rounded border px-3 py-2 text-left text-xs hover:bg-muted/50"
                  @click="openDetail(change)"
                >
                  <strong>{{ change.name }}</strong>
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

      <Card v-if="showingStrategyBody">
        <CardHeader class="flex-row flex-wrap items-center justify-between gap-3">
          <div><CardTitle>趋势排名</CardTitle><CardDescription>{{ scope }} · 完整股票池筛选后再虚拟滚动</CardDescription></div>
          <div
            class="flex gap-1"
            aria-label="按趋势状态筛选"
            data-testid="trend-state-filter"
          >
            <Button
              v-for="item in stateFilters"
              :key="item.value"
              size="sm"
              :variant="stateFilter === item.value ? 'secondary' : 'ghost'"
              :aria-pressed="stateFilter === item.value"
              @click="stateFilter = item.value"
            >
              {{ item.label }}
            </Button>
          </div>
          <label class="flex items-center gap-2 text-sm text-muted-foreground">搜索
            <input
              v-model="rankingSearch"
              type="search"
              aria-label="按名称或代码搜索趋势股票"
              placeholder="股票名称或代码"
              class="h-9 w-56 rounded-md border bg-background px-3 text-foreground"
              data-testid="trend-ranking-search"
            >
          </label>
          <label class="flex items-center gap-2 text-sm text-muted-foreground">排序指标
            <select
              v-model="sortKey"
              aria-label="排名排序指标"
              class="h-9 rounded-md border bg-background px-2 text-foreground"
            >
              <option
                v-for="column in rankingColumns"
                :key="column.key"
                :value="column.key"
              >{{ column.label }}</option>
            </select>
          </label>
        </CardHeader>
        <CardContent class="px-0">
          <Empty v-if="!loading && !items.length">
            <EmptyHeader><EmptyTitle>暂无趋势快照</EmptyTitle><EmptyDescription>请确认所选日期已完成收盘行情同步和策略计算。</EmptyDescription></EmptyHeader>
          </Empty>
          <div
            v-else
            ref="rankingViewport"
            class="w-full overflow-auto [&_[data-slot=table-container]]:overflow-visible"
            :class="virtualRanking ? 'max-h-[680px]' : ''"
            data-testid="trend-ranking-scroll"
            tabindex="0"
            aria-label="完整趋势排名，滚动查看全部股票"
            @scroll="rankingScrollTop = ($event.target as HTMLElement).scrollTop"
          >
            <Table
              class="w-full"
              :aria-rowcount="sortedItems.length + 2"
            >
              <TableHeader>
                <TableRow>
                  <th
                    v-for="group in rankingGroups"
                    :key="group.label"
                    :colspan="group.count"
                    class="border-r px-4 py-2 text-left text-xs text-muted-foreground"
                  >
                    {{ group.label }}
                  </th>
                </TableRow>
                <TableRow>
                  <SortableTableHeader
                    v-for="column in rankingColumns"
                    :key="column.key"
                    :label="column.label"
                    class="min-w-32 whitespace-nowrap"
                    :class="column.key === 'name' ? 'sticky left-0 z-20 min-w-48 bg-background' : ''"
                    :description="column.description"
                    :active="sortKey === column.key"
                    :direction="sortDirection"
                    @sort="toggleSort(column.key)"
                  />
                </TableRow>
              </TableHeader>
              <TableBody>
                <tr
                  v-if="virtualStart"
                  aria-hidden="true"
                  :style="{ height: `${virtualStart * rankingRowHeight}px` }"
                >
                  <td
                    :colspan="rankingColumns.length"
                    class="p-0"
                  />
                </tr>
                <TableRow
                  v-for="(item, index) in renderedRankingRows"
                  :key="item.code"
                  class="cursor-pointer"
                  data-testid="trend-row"
                  :aria-rowindex="virtualStart + index + 3"
                  :style="virtualRanking ? { height: `${rankingRowHeight}px` } : undefined"
                  @click="openDetail(item)"
                >
                  <TableCell
                    v-for="column in rankingColumns"
                    :key="column.key"
                    class="min-w-32 whitespace-nowrap tabular-nums"
                    :class="column.key === 'name' ? 'sticky left-0 z-10 min-w-48 bg-background' : column.key === 'alphaScore' ? 'font-bold text-primary' : ''"
                    :data-column="column.key"
                  >
                    <template v-if="column.key === 'rank'">
                      #{{ item.rank }}
                    </template>
                    <template v-else-if="column.key === 'name'">
                      <strong class="block">{{ item.name }}</strong><span class="font-mono text-xs text-muted-foreground">{{ item.code }}</span>
                    </template>
                    <Badge
                      v-else-if="column.key === 'state'"
                      :variant="badgeVariant(item.state)"
                    >
                      {{ stateText(item.state) }}
                    </Badge>
                    <template v-else-if="column.key === 'trendLifecycle'">
                      <span class="text-xs">{{ item.trendLifecycle ?? '—' }}</span><span class="block text-xs text-muted-foreground">{{ item.trendDurationDays == null ? '—' : `${item.trendDurationDays}D` }}</span>
                    </template>
                    <template v-else-if="column.key === 'rankChange5D'">
                      <div
                        class="flex gap-3 whitespace-nowrap"
                        data-testid="trend-rank-changes"
                      >
                        <span
                          v-for="[label, value] in ([['1D', item.rankChange1D], ['3D', item.rankChange3D], ['5D', item.rankChange5D]] as const)"
                          :key="label"
                          class="text-xs"
                        >
                          <span class="text-muted-foreground">{{ label }}</span>
                          <span :class="value == null || value === 0 ? 'text-muted-foreground' : value > 0 ? 'text-market-up' : 'text-market-down'">
                            {{ rankDelta(value) }}
                          </span>
                        </span>
                      </div>
                    </template>
                    <template v-else-if="column.key === 'alphaScore'">
                      {{ score(item.alphaScore) }}<span class="block text-xs font-normal text-muted-foreground">{{ item.features.alphaVersion === 2 ? 'V2' : 'V1' }}</span>
                    </template>
                    <template v-else>
                      {{ rankingCell(item, column) }}
                    </template>
                  </TableCell>
                </TableRow>
                <tr
                  v-if="rankingBottomSpace"
                  aria-hidden="true"
                  :style="{ height: `${rankingBottomSpace}px` }"
                >
                  <td
                    :colspan="rankingColumns.length"
                    class="p-0"
                  />
                </tr>
              </TableBody>
            </Table>
          </div>
          <p
            v-if="items.length && !sortedItems.length"
            class="px-6 pt-4 text-sm text-muted-foreground"
            role="status"
          >
            没有匹配的股票，请尝试其他名称、代码或 State 筛选。
          </p>
          <p
            v-if="items.length"
            class="px-6 pt-4 text-sm text-muted-foreground"
            data-testid="trend-ranking-count"
          >
            显示 {{ sortedItems.length }} / {{ items.length }} 条
          </p>
        </CardContent>
      </Card>
    </div>

    <Dialog
      :open="detailOpen"
      @update:open="value => { detailOpen = value; if (!value) ++detailRequestId; }"
    >
      <DialogContent
        class="max-h-[calc(100dvh-2rem)] min-w-0 overflow-y-auto p-4 sm:max-w-4xl sm:p-6"
        data-testid="trend-detail"
      >
        <DialogHeader class="min-w-0 pr-8 text-left">
          <DialogTitle class="break-words">
            {{ detail?.metadata.name || '趋势详情' }}
          </DialogTitle><DialogDescription>{{ detail?.metadata.code }} · 趋势指标、风险与状态历史</DialogDescription>
        </DialogHeader>
        <div
          v-if="detailLoading"
          class="min-w-0 space-y-3"
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
          class="min-w-0 space-y-5"
        >
          <div class="flex flex-wrap gap-2">
            <Badge :variant="badgeVariant(detail.latest.state)">
              {{ stateText(detail.latest.state) }}
            </Badge><Badge variant="outline">
              {{ detail.latest.setup }}
            </Badge>
          </div>
          <div class="grid grid-cols-3 gap-3 rounded-lg border p-4 text-sm">
            <div>Trend Age<strong class="block">{{ detail.latest.trendDurationDays == null ? '—' : `${detail.latest.trendDurationDays}D` }}</strong></div>
            <div>Lifecycle<strong class="block">{{ detail.latest.trendLifecycle ?? '—' }}</strong></div>
            <div>Fragility<strong class="block">{{ score(detail.latest.fragilityScore) }} / 100</strong></div>
            <div>Trend Quality<strong class="block">{{ score(detail.latest.features.trendQuality) }}</strong></div>
            <div>Acceleration<strong class="block">{{ score(detail.latest.features.trendAcceleration) }}</strong></div>
            <div>Signed Efficiency<strong class="block">{{ score(detail.latest.features.signedEfficiencyRatio10D) }}</strong></div>
          </div>
          <details class="rounded-lg border p-4 text-sm">
            <summary class="cursor-pointer">
              Fragility Breakdown
            </summary>
            <p class="my-2 text-xs text-muted-foreground">
              与 3 / 5 个历史正式快照日比较；缺失项不计权重，数据不足不生成总分。
            </p>
            <dl class="grid grid-cols-2 gap-2">
              <div
                v-for="(value, key) in detail.latest.fragilityBreakdown"
                :key="key"
              >
                <dt>{{ key }}</dt><dd>{{ score(value) }}</dd>
              </div>
            </dl>
          </details>
          <p
            v-if="detailMode === 'preview'"
            class="text-xs text-muted-foreground"
          >
            当前详情为 Preview；图表最后一个空心点为 Preview，不属于正式历史。
          </p>
          <p
            v-if="historyLoading"
            class="text-sm text-muted-foreground"
          >
            正在加载正式历史…
          </p>
          <AppApiErrorAlert
            v-if="historyError"
            :error="historyError"
            action-label="重试历史加载"
            @action="loadDetailHistory"
            @dismiss="historyError = null"
          />
          <TrendFragilityHistoryChart
            v-if="detailChartHistory.length"
            :history="detailChartHistory"
          />
          <TrendRankHistoryChart
            :history="detailChartHistory"
          />
          <section
            class="grid grid-cols-2 gap-3 text-sm"
            data-testid="trend-path-detail"
          >
            <div>Alpha {{ detail.latest.features.alphaVersion === 2 ? 'V2' : 'V1' }}<strong class="block">{{ score(detail.latest.alphaScore) }}</strong></div>
            <div>
              <IndicatorLabel
                label="Path Score"
                :description="descriptions.path"
              /><strong class="block">{{ score(detail.latest.features.pathScore) }}</strong>
            </div>
            <div>
              <IndicatorLabel
                label="Setup Score"
                :description="descriptions.breakout"
              /><strong class="block">{{ score(detail.latest.features.setupScore) }}</strong>
            </div>
            <div>
              <IndicatorLabel
                label="Return Concentration"
                :description="descriptions.concentration"
              /><strong class="block">{{ pct(detail.latest.features.positiveReturnConcentration) }}</strong>
            </div>
            <div>
              <IndicatorLabel
                label="ATR Expansion"
                :description="descriptions.expansion"
              /><strong class="block">{{ detail.latest.features.atrExpansionRatio?.toFixed(2) ?? '—' }}</strong>
            </div>
            <div>
              <IndicatorLabel
                label="Downside Control"
                :description="descriptions.downside"
              /><strong class="block">{{ score(detail.latest.features.downsideControlQuality) }} / ratio {{ detail.latest.features.downsideUpsideRatio?.toFixed(2) ?? '—' }}</strong>
            </div>
          </section>
          <section>
            <h3 class="mb-2 font-semibold">
              <IndicatorLabel
                label="Alpha Score Breakdown"
                :description="descriptions.alpha"
              />
            </h3>
            <div
              v-if="alphaContributions.length"
              class="mb-3 grid grid-cols-2 gap-2 text-sm"
              data-testid="trend-alpha-contributions"
            >
              <div
                v-for="part in alphaContributions"
                :key="part.key"
                class="rounded border p-2"
              >
                <strong class="uppercase">{{ part.key }}</strong>
                <span class="block">{{ score(part.value) }} × {{ pct(part.weight) }} = {{ score(part.contribution) }} 分</span>
              </div>
            </div>
            <pre class="overflow-x-auto rounded bg-muted p-3 text-xs">{{ JSON.stringify(detail.latest.scoreBreakdown, null, 2) }}</pre>
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
                /><strong class="block">{{ detail.latest.features.weightedR2?.toFixed(3) ?? '—' }}</strong>
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
            <IndicatorLabel
              label="ATR"
              :description="descriptions.atr"
              wrap
            />
            <strong class="block">{{ price(detail.latest.atr) }}</strong>
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
                <span>{{ snapshot.tradeDate }}</span><span>排名 {{ snapshot.rank > 0 ? `#${snapshot.rank}` : '—' }}</span><span>Alpha {{ score(snapshot.alphaScore) }}</span><Badge :variant="badgeVariant(snapshot.state)">
                  {{ stateText(snapshot.state) }}
                </Badge>
              </div>
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>
