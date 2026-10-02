<script setup lang="ts">
import TrendEventStudy from '@/components/trend-following/TrendEventStudy.vue';
import { alphaVersionLabel } from '@/utils/trendFollowing';
import { exportExcel, type ExcelColumn } from '@/utils/excelExport';
import { forwardReturnColumns, useForwardReturns } from '@/composables/useForwardReturns';
import { parseDate } from '@internationalized/date';
import DailyKLineCard from '@/components/market-data/DailyKLineCard.vue';
import { detailChartHistory as buildDetailChartHistory } from '@/utils/detailChartHistory';
import ResearchMarketToggle from '@/components/research/ResearchMarketToggle.vue';
import { useRoute } from 'vue-router';
import { useLazyResearchPreview } from '@/composables/useLazyResearchPreview';
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue';
import { RefreshCcw } from 'lucide-vue-next';
import { toast } from 'vue-sonner';
import { trendFollowingApi } from '@/api/trendFollowing';
import { createParsedApiError, getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import BilingualEnum from '@/components/app/BilingualEnum.vue';
import BilingualLabel from '@/components/app/BilingualLabel.vue';
import IndicatorLabel from '@/components/app/IndicatorHelpLabel.vue';
import { metricLabel } from '@/i18n/labels';
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
const rankingDetailTrigger = ref<{ code: string; el: HTMLElement | null } | null>(null);
const alphaContributions = computed(() => {
  const alpha = detail.value?.latest.scoreBreakdown.alpha as TrendAlphaBreakdown | undefined;
  if (!alpha) return [];
  return ['trend', 'rs', 'setup', 'path'].map(key => ({
    key, value: alpha.components[key], weight: alpha.weights[key], contribution: alpha.contributions[key],
  }));
});

const entryBranches = computed(() => {
  const entry = detail.value?.latest.features.entryBreakdown;
  return entry ? [{ label: 'BREAKOUT', data: entry.breakout }, { label: 'PULLBACK_RESUME', data: entry.resume }] : [];
});
const entryComponentLabels: Record<string, string> = {
  breakout: 'Breakout Quality', extension: 'Extension Quality', clv: 'CLV Quality',
  volume: 'Volume Quality', rs: 'RS Quality', path: 'Path Quality', fragility: 'Fragility Quality',
  reclaim: 'Reclaim Quality', pullbackDepth: 'Pullback Depth Quality', distance: 'MA20 Distance Quality',
};
const entryCheckLabels: Record<string, string> = {
  rsScore: 'RS门槛', alphaScore: 'Alpha门槛', pathScore: 'Path门槛', trendScore: 'Trend门槛',
  ma20Rising: 'MA20上升', rs10Positive: 'RS10为正', fragility: 'Fragility门槛',
  breakout: '突破形态', extension: 'MA20距离', clv: '收盘位置', resume: '回踩恢复', structure: '均线结构',
};
const historyLoading = ref(false);
const historyError = ref<ParsedApiError | null>(null);
let detailRequestId = 0;
const detailChartHistory = computed(() => detail.value
  ? buildDetailChartHistory(detail.value.history, detail.value.latest, detailMode.value === 'preview')
  : []);
const trendColumns = [
  { key: 'rank', label: 'alphaRank', group: 'Core', format: 'number', description: descriptions.rank },
  { key: 'name', label: '股票名称', group: 'Core', format: 'text', description: undefined },
  { key: 'state', label: 'state', group: 'Core', format: 'text', description: descriptions.state },
  { key: 'alphaScore', label: 'alphaScore', group: 'Core', format: 'score', description: descriptions.alpha },
  { key: 'entryScore', label: 'entryScore', group: 'Core', format: 'score', description: descriptions.entry },
  { key: 'entryType', label: 'entryType', group: 'Core', format: 'text', description: descriptions.entry },
  { key: 'trendScore', label: 'trendScore', group: 'Core', format: 'score', description: descriptions.trend },
  { key: 'rsScore', label: 'rsScore', group: 'Core', format: 'score', description: descriptions.relativeStrength },
  { key: 'setupScore', label: 'setupScore', group: 'Core', format: 'score', description: descriptions.breakout },
  { key: 'pathScore', label: 'pathScore', group: 'Core', format: 'score', description: descriptions.path },
  { key: 'distanceFromMa20', label: 'distanceFromMa20', group: 'Core', format: 'percent', description: descriptions.movingAverage },
  { key: 'atrPercent', label: 'atrPercent', group: 'Core', format: 'percent', description: descriptions.atrPercent },
  { key: 'fragilityScore', label: 'fragility', group: 'Core', format: 'score', description: '0–100；越高表示内部恶化越快。历史不足显示 —，并不代表稳定。' },
  { key: 'closeLocationValue', label: 'clv', group: 'Core', format: 'ratio', description: descriptions.clv },
  ...forwardReturnColumns,
  { key: 'trendLifecycle', label: 'lifecycleAge', group: 'Core', format: 'number', description: '趋势阶段与持续交易日数。MATURE 表示趋势成熟阶段。' },
  { key: 'rankChange5D', label: '排名趋势', group: 'Core', format: 'number', description: descriptions.rankChange },
  { key: 'referencePrice', label: 'referencePrice', group: 'Core', format: 'price', description: descriptions.reference },
  { key: 'alphaTrendContribution', label: 'Trend Contribution', group: 'Alpha', format: 'score', description: descriptions.alpha },
  { key: 'alphaRsContribution', label: 'RS Contribution', group: 'Alpha', format: 'score', description: descriptions.alpha },
  { key: 'alphaSetupContribution', label: 'Setup Contribution', group: 'Alpha', format: 'score', description: descriptions.alpha },
  { key: 'alphaPathContribution', label: 'Path Contribution', group: 'Alpha', format: 'score', description: descriptions.alpha },
  { key: 'weightedSlopePercentile', label: 'Slope Percentile 15D', group: 'Trend', format: 'score', description: descriptions.slopePercentile },
  { key: 'r2Quality', label: 'R² Quality', group: 'Trend', format: 'score', description: descriptions.r2Quality },
  { key: 'momentumQuality', label: 'Momentum Quality', group: 'Trend', format: 'score', description: descriptions.momentumQuality },
  { key: 'return10DQuality', label: 'Return 10D Quality', group: 'Trend', format: 'score', description: descriptions.returnQuality },
  { key: 'return20DQuality', label: 'Return 20D Quality', group: 'Trend', format: 'score', description: descriptions.returnQuality },
  { key: 'drawdownQuality', label: 'Drawdown Quality', group: 'Trend', format: 'score', description: descriptions.drawdownQuality },
  { key: 'rs5DQuality', label: 'RS 5D Quality', group: 'RS', format: 'score', description: descriptions.rsQuality },
  { key: 'rs10DQuality', label: 'RS 10D Quality', group: 'RS', format: 'score', description: descriptions.rsQuality },
  { key: 'rs20DQuality', label: 'RS 20D Quality', group: 'RS', format: 'score', description: descriptions.rsQuality },
  { key: 'breakoutQuality', label: 'Breakout Quality', group: 'Setup', format: 'score', description: descriptions.breakout },
  { key: 'extensionQuality', label: 'Extension Quality', group: 'Setup', format: 'score', description: descriptions.breakout },
  { key: 'volumeQuality', label: 'Volume Quality', group: 'Setup', format: 'score', description: descriptions.breakout },
  { key: 'compressionQuality', label: 'Compression Quality', group: 'Setup', format: 'score', description: descriptions.breakout },
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
  { key: 'trendAcceleration', label: 'Trend Acceleration', group: 'Risk / Health', format: 'score', description: undefined },
] as const;
const boxColumns = [
  { key: 'name', label: '股票名称', format: 'text' },
  { key: 'boxState', label: '状态', format: 'text' },
  { key: 'boxQuality', label: 'boxQuality', format: 'score' },
  { key: 'boxWindowDays', label: 'boxDays', format: 'number' },
  { key: 'boxWidthPct', label: 'boxWidth', format: 'percent' },
  { key: 'distanceToBoxHighPct', label: '距箱顶', format: 'percent' },
  { key: 'boxBreakoutDistanceAtr', label: '突破距离', format: 'ratio' },
  { key: 'boxUpperTouches', label: '上沿测试', format: 'number' },
  { key: 'rsScore', label: 'rsScore', format: 'score' },
  { key: 'trendScore', label: 'trendScore', format: 'score' },
  { key: 'alphaScore', label: 'alpha', format: 'score' },
  { key: 'volumeRatio', label: 'volume', format: 'ratio' },
  ...forwardReturnColumns,
] as const;
const mrColumns = [
  { key: 'name', label: '股票名称', format: 'text' },
  { key: 'mrState', label: 'mrState', format: 'text' },
  { key: 'mrQuality', label: 'mrQuality', format: 'score' },
  { key: 'rsi14', label: 'RSI14', format: 'score' },
  { key: 'distanceFromMa20Atr', label: '距 MA20 / ATR', format: 'ratio' },
  { key: 'return3D', label: 'return3D', format: 'percent' },
  { key: 'return5D', label: 'return5D', format: 'percent' },
  { key: 'closeLocationValue', label: 'clv', format: 'ratio' },
  { key: 'trendScore', label: 'trendScore', format: 'score' },
  { key: 'rsScore', label: 'rsScore', format: 'score' },
  { key: 'alphaScore', label: 'alpha', format: 'score' },
  { key: 'state', label: 'state', format: 'text' },
] as const;
const mrFilters = [{ value: 'all', label: '全部超跌机会' }, { value: 'MR_REBOUND', label: '反弹确认' }, { value: 'MR_OVERSOLD', label: '超跌观察' }];
const mrText = (value: unknown) => value === 'MR_REBOUND' ? '反弹确认' : value === 'MR_OVERSOLD' ? '超跌观察' : '—';
const mrPriority = (row: TrendRankingSnapshot) => row.features.mrState === 'MR_REBOUND' ? 0 : 1;
type ColumnSource = typeof trendColumns[number] | typeof boxColumns[number] | typeof mrColumns[number];
type RankingColumn = { key: ColumnSource['key']; label: string; format: ColumnSource['format']; group: string; description?: string };
type SortKey = RankingColumn['key'];
const boxFilters = [
  { value: 'opportunities', label: '全部机会' }, { value: 'BOX_BREAKOUT', label: '刚突破' },
  { value: 'BOX_READY', label: '待突破' }, { value: 'BOX_FORMING', label: '形成中' },
];
function boxStateText(state: unknown) {
  return state === 'BOX_BREAKOUT' ? '刚突破' : state === 'BOX_READY' ? '待突破' : state === 'BOX_FORMING' ? '整理中' : '—';
}
const boxPriority = (item: TrendRankingSnapshot) => item.features.boxState === 'BOX_BREAKOUT' ? 0
  : item.features.boxState === 'BOX_READY' ? 1 : item.features.boxState === 'BOX_FORMING' ? 2 : 3;
function defaultBoxSort(left: TrendRankingSnapshot, right: TrendRankingSnapshot) {
  return boxPriority(left) - boxPriority(right)
    || (right.features.boxQuality ?? -1) - (left.features.boxQuality ?? -1)
    || right.alphaScore - left.alphaScore || left.code.localeCompare(right.code);
}
const boxDetailFields = [
  ['boxQuality', 'Box Quality', 'score'], ['boxWindowDays', '周期', 'days'],
  ['boxHigh', '箱顶', 'price'], ['boxLow', '箱底', 'price'], ['boxWidthPct', '宽度', 'percent'],
  ['distanceToBoxHighPct', '距箱顶', 'distance'], ['boxBreakoutDistanceAtr', '突破 ATR', 'atr'],
  ['boxUpperTouches', '上沿测试次数', 'count'], ['boxLowerTouches', '下沿测试次数', 'count'],
  ['boxSlopeAtr', '窗口趋势 / ATR', 'score'], ['boxRSquared', 'R²', 'score'],
  ['boxOccupancy', '内部占用', 'percent'], ['boxAtr20', '昨日 ATR20', 'price'],
  ['boxWidthQuality', 'Width Quality', 'score'], ['boxFlatnessQuality', 'Flatness Quality', 'score'],
  ['boxOccupancyQuality', 'Occupancy Quality', 'score'], ['boxCompressionQuality', 'Compression Quality', 'score'],
  ['boxTouchQuality', 'Touch Quality', 'score'],
] as const;
function boxDetailValue(key: typeof boxDetailFields[number][0], format: string) {
  const value = detail.value?.latest.features[key];
  if (value == null) return '—';
  if (format === 'distance') return pct(-value);
  if (format === 'percent') return pct(value);
  if (format === 'price') return price(value);
  if (format === 'days') return `${value}d`;
  if (format === 'count') return String(value);
  if (format === 'atr') return `${value > 0 ? '+' : ''}${value.toFixed(2)} ATR`;
  return score(value);
}
type StateFilter = 'all' | 'CANDIDATE' | 'TRENDING' | 'WEAKENING' | 'BROKEN';
const stateFilters: Array<{ value: StateFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'CANDIDATE', label: '趋势候选' },
  { value: 'TRENDING', label: '趋势健康' },
  { value: 'WEAKENING', label: '趋势弱化' },
  { value: 'BROKEN', label: '趋势破坏' },
];
let generation = 0;
const marketOverviewRefreshKey = ref(0);
const marketOverviewReady = ref(false);
const studyContextReady = ref(false);
const detailMode = ref<ResearchDataMode>('official');

const scope = computed(() => market.value === 'CN' ? '沪深300 + 中证500' : 'S&P 500');
const ITEM_SORT_KEYS = ['rank', 'name', 'state', 'setup', 'alphaScore', 'trendScore', 'rsScore',
  'referencePrice', 'fragilityScore', 'entryScore', 'entryType'] as const;
type ItemSortKey = Extract<SortKey, typeof ITEM_SORT_KEYS[number]>;
type RankingColumnFeatureKey = Extract<SortKey, RankingFeatureKey>;
function isItemSortKey(key: SortKey): key is ItemSortKey {
  return ITEM_SORT_KEYS.some(item => item === key);
}
function isRankingFeatureKey(key: SortKey): key is RankingColumnFeatureKey {
  return RANKING_FEATURE_KEYS.some(item => item === key);
}
function sortValue(item: TrendRankingSnapshot, key: SortKey): string | number | boolean | null {
  if (key === 'mrState') return mrPriority(item);
  if (key === 'boxState') return boxPriority(item);
  if (key.startsWith('forwardReturn')) return forwardReturn(item.code, key);
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
function rankingCell(item: TrendRankingSnapshot, column: RankingColumn) {
  const value = sortValue(item, column.key);
  if (column.key === 'volumeRatio' && item.features.volumeProvisional) return '盘中估算 —';
  if (column.key === 'volumeQuality' && item.features.volumeProvisional) return `${value == null ? '—' : score(Number(value))}（暂定）`;
  if (value == null) return '—';
  if (column.key === 'mrState') return mrText(item.features.mrState);
  if (column.key === 'boxState') return boxStateText(item.features.boxState);
  if (column.key === 'boxWindowDays') return `${value}d`;
  if (column.key === 'distanceToBoxHighPct') return pct(-Number(value));
  if (column.key === 'boxBreakoutDistanceAtr') return `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(2)} ATR`;
  if (column.key === 'boxUpperTouches') return String(value);
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
async function exportRanking(table: typeof tables[number]) {
  if (table.exporting || loading.value || refreshing.value || previewLoading.value || forwardLoading.value || !table.sortedItems.length) return;
  table.exporting = true;
  try {
    const columns: ExcelColumn[] = table.columns.flatMap(column => {
      const zh = metricLabel(column.label).zh;
      if (column.key === 'name') return [{ label: zh }, { label: '代码' }];
      if (column.key === 'trendLifecycle') return [{ label: metricLabel('lifecycle').zh }, { label: '持续天数', format: '0' }];
      if (column.key === 'rankChange5D') return ['1D', '3D', '5D'].map(period => ({ label: `排名变化${period}`, format: '+0;-0;0' }));
      if (column.key === 'alphaScore') return [{ label: zh, format: '0.0' }, { label: 'Alpha 版本' }];
      return [{ label: zh, format: column.format === 'percent' ? '0.0%'
        : column.format === 'r2' ? '0.000' : column.format === 'slope' ? '0.0000'
          : column.format === 'price' || column.format === 'ratio' ? '0.00' : column.key === 'rank' ? '0' : '0.0' }];
    });
    const rows = table.sortedItems.map(item => table.columns.flatMap(column => {
      if (column.key === 'name') return [item.name, item.code];
      if (column.key === 'state') return [stateText(item.state)];
      if (column.key === 'mrState') return [mrText(item.features.mrState)];
      if (column.key === 'boxState') return [boxStateText(item.features.boxState)];
      if (column.key === 'distanceToBoxHighPct') return [item.features.distanceToBoxHighPct == null ? null : -item.features.distanceToBoxHighPct];
      if (column.key === 'trendLifecycle') return [item.trendLifecycle, item.trendDurationDays];
      if (column.key === 'rankChange5D') return [item.rankChange1D, item.rankChange3D, item.rankChange5D];
      if (column.key === 'alphaScore') return [item.alphaScore, alphaVersionLabel(item.features.alphaVersion as number | null | undefined)];
      if (column.key === 'volumeRatio' && item.features.volumeProvisional === true) return [null];
      return [sortValue(item, column.key)];
    }));
    await exportExcel(`${table.kind === 'trend' ? '趋势分析' : table.title}_${market.value}_${summary.value.tradeDate}_${dataMode.value}.xlsx`, '趋势分析', columns, rows);
  } catch {
    toast.error('Excel 导出失败，请重试');
  } finally {
    table.exporting = false;
  }
}

const { value: forwardReturn, error: forwardError, loading: forwardLoading, retry: retryForward } =
  useForwardReturns(items, market, () => summary.value.tradeDate, dataMode);
// Each section owns its filters, ordering and scroll viewport. All share the same snapshot and drawer.
function createTable(kind: 'trend' | 'box' | 'mr', title: string, description: string, columns: readonly RankingColumn[]) {
  const search = ref('');
  const filter = ref(kind === 'box' ? 'opportunities' : 'all');
  const sortKey = ref<SortKey>(kind === 'trend' ? 'rank' : kind === 'box' ? 'boxState' : 'mrState');
  const sortDirection = ref<'asc' | 'desc'>('asc');
  const viewport = shallowRef<HTMLElement | null>(null);
  const scrollTop = ref(0);
  const filteredItems = computed(() => {
    const query = search.value.trim().toLocaleLowerCase();
    return items.value.filter(item => {
      if (kind === 'box') {
        const state = item.features.boxState;
        if (filter.value === 'opportunities' ? state !== 'BOX_BREAKOUT' && state !== 'BOX_READY' : state !== filter.value) return false;
      } else if (kind === 'mr') {
        const state = item.features.mrState;
        if (filter.value === 'all' ? state !== 'MR_REBOUND' && state !== 'MR_OVERSOLD' : state !== filter.value) return false;
      } else if (filter.value !== 'all' && item.state !== filter.value) return false;
      return !query || item.code.toLocaleLowerCase().includes(query) || item.name.toLocaleLowerCase().includes(query);
    });
  });
  const sortedItems = computed(() => [...filteredItems.value].sort((left, right) => {
    const direction = sortDirection.value === 'asc' ? 1 : -1;
    if (kind === 'mr' && sortKey.value === 'mrState') return (mrPriority(left) - mrPriority(right)
      || (right.features.mrQuality ?? -1) - (left.features.mrQuality ?? -1) || left.code.localeCompare(right.code)) * direction;
    if (kind === 'box' && sortKey.value === 'boxState') return defaultBoxSort(left, right) * direction;
    const a = sortValue(left, sortKey.value), b = sortValue(right, sortKey.value);
    if (a == null) return b == null ? left.code.localeCompare(right.code) : 1;
    if (b == null) return -1;
    const comparison = typeof a !== 'string' && typeof b !== 'string' ? Number(a) - Number(b) : String(a).localeCompare(String(b));
    return comparison * direction || left.code.localeCompare(right.code);
  }));
  const virtual = computed(() => sortedItems.value.length > 300);
  const virtualStart = computed(() => virtual.value
    ? Math.min(Math.max(0, sortedItems.value.length - 28), Math.max(0, Math.floor((scrollTop.value - 80) / 64) - 8)) : 0);
  const renderedRows = computed(() => virtual.value ? sortedItems.value.slice(virtualStart.value, virtualStart.value + 28) : sortedItems.value);
  const bottomSpace = computed(() => virtual.value ? Math.max(0, sortedItems.value.length - virtualStart.value - renderedRows.value.length) * 64 : 0);
  watch(sortedItems, () => { scrollTop.value = 0; if (viewport.value) viewport.value.scrollTop = 0; });
  function toggleSort(key: SortKey) {
    sortDirection.value = sortKey.value === key ? sortDirection.value === 'asc' ? 'desc' : 'asc'
      : ['rank', 'name', 'setup', 'state', 'trendCandidate', 'priorCompression', 'compressionBreakout', 'trendResume'].includes(key) ? 'asc' : 'desc';
    sortKey.value = key;
  }
  return reactive({ kind, title, description, columns, exporting: false, search, filter, sortKey, sortDirection, viewport, scrollTop,
    sortedItems, virtual, virtualStart, renderedRows, bottomSpace, toggleSort,
    groups: [...new Set(columns.map(c => c.group))].map(label => ({ label, count: columns.filter(c => c.group === label).length })),
  });
}
const tables = [
  createTable('trend', '趋势排名', '已形成趋势及趋势候选，按 Alpha/趋势质量研究。', trendColumns),
  createTable('box', '结构机会', '识别正在形成、接近突破或刚突破的横盘结构。', boxColumns.map(c => ({ ...c, group: '箱体结构' }))),
  createTable('mr', '超跌反弹', '识别短期极端偏离及确认反弹，不参与 Alpha 排名。', mrColumns.map(c => ({ ...c, group: '超跌反弹' }))),
];
const cards = computed(() => [
  ['marketRegime', summary.value.marketRegime, descriptions.marketRegime, 'enum'],
  ['marketScore', score(summary.value.marketScore), descriptions.marketScore, 'text'],
  ['universeSize', summary.value.universeSize, descriptions.universeSize, 'text'],
  ['dataCoverage', pct(summary.value.dataCoverage), descriptions.dataCoverage, 'text'],
  ['rankable', summary.value.rankableCount, descriptions.rankable, 'text'],
  ['candidate', summary.value.candidateCount, descriptions.candidate, 'text'],
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
function stateText(state: TrendState | null) {
  if (state == null) return '—';
  return ({ IDLE: '无明显趋势', WATCHING: '趋势形成', CANDIDATE: '趋势候选', TRENDING: '趋势健康',
    WEAKENING: '趋势弱化', BROKEN: '趋势破坏' })[state];
}
function badgeVariant(value: string | null): 'default' | 'success' | 'warning' | 'destructive' | 'info' | 'outline' {
  if (value == null) return 'outline';
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
      const parsed = getParsedApiError(reason);
      error.value = parsed.status === 404 ? null : parsed;
      items.value = [];
      changes.value = null;
      officialSelected.value = null;
    }
  } finally {
    if (current === generation) {
      marketOverviewReady.value = true;
      studyContextReady.value = true;
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
function rankingRowElement(event: Event): HTMLElement | null {
  return event.currentTarget instanceof HTMLElement ? event.currentTarget : null;
}
function restoreRankingFocus() {
  const trigger = rankingDetailTrigger.value;
  rankingDetailTrigger.value = null;
  if (!trigger) return;
  void nextTick(() => {
    const connected = trigger.el?.isConnected ? trigger.el : null;
    const row = connected ?? tables.flatMap(table => Array.from(table.viewport?.querySelectorAll('[data-code]') ?? []))
      .find(element => element.getAttribute('data-code') === trigger.code);
    if (row instanceof HTMLElement) row.focus();
  });
}
function onDetailOpenChange(open: boolean) {
  detailOpen.value = open;
  if (open) return;
  ++detailRequestId;
  restoreRankingFocus();
}
function openRankingDetail(item: TrendRankingSnapshot, event: Event) {
  rankingDetailTrigger.value = { code: item.code, el: rankingRowElement(event) };
  void openDetail(item);
}
function onRankingRowKeydown(item: TrendRankingSnapshot, event: KeyboardEvent) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  openRankingDetail(item, event);
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
  studyContextReady.value = false;
  ++detailRequestId;
  selectedDate.value = '';
  tables.forEach(table => { table.search = ''; });
  tables.forEach(table => { table.filter = table.kind === 'box' ? 'opportunities' : 'all'; });
  officialSelected.value = null;
  officialLatest.value = null;
  resetPreview();
  items.value = [];
  changes.value = null;
  availableDates.value = [];
  detailOpen.value = false;
  rankingDetailTrigger.value = null;
  summary.value = { ...emptySummary(), market: market.value };
  modeChosenByUser.value = false;
  void load(true, { autoSelectMode: true });
});
function setMarket(target: TrendMarket) {
  if (market.value === target) return;
  market.value = target;
}
let entryDisposed = false;
onBeforeUnmount(() => { entryDisposed = true; });
onMounted(async () => {
  const symbol = typeof route?.query?.symbol === 'string' ? route.query.symbol : '';
  let date = '';
  try { if (typeof route?.query?.tradeDate === 'string') date = parseDate(route.query.tradeDate).toString(); } catch { /* Ignore invalid links. */ }
  const entryMarket = market.value;
  if (date) { selectedDate.value = date; dataMode.value = 'official'; modeChosenByUser.value = true; }
  await load(true, { autoSelectMode: !date });
  if (!entryDisposed && symbol && date && market.value === entryMarket && selectedDate.value === date) {
    await openDetail({ code: symbol, tradeDate: date, preview: false });
  }
});
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
        class="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-6"
        data-testid="trend-summary"
      >
        <Card
          v-for="card in cards"
          :key="String(card[0])"
        >
          <CardContent class="min-w-0 p-3">
            <IndicatorLabel
              :label="String(card[0])"
              :description="String(card[2])"
              wrap
            />
            <BilingualEnum
              v-if="card[3] === 'enum'"
              :value="String(card[1] ?? '')"
              size="badge"
              class="mt-1"
            />
            <strong
              v-else
              class="mt-1 block truncate text-lg tabular-nums"
            >{{ card[1] }}</strong>
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
                label="marketScoreDelta"
                :description="descriptions.marketScoreChange"
              />
              <strong class="mt-1 block text-lg">{{ scoreDelta(changes?.marketScoreChange) }}</strong>
            </div>
            <div
              class="rounded border p-3"
              data-testid="trend-breadth-score-change"
            >
              <IndicatorLabel
                label="breadthScoreDelta"
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

      <template v-if="showingStrategyBody">
        <Card
          v-for="table in tables"
          :id="`section-${table.kind}`"
          :key="table.kind"
          :data-testid="`${table.kind}-section`"
        >
          <CardHeader class="flex flex-row flex-wrap items-center justify-between gap-3">
            <div><CardTitle>{{ table.title }}</CardTitle><CardDescription>{{ table.description }}</CardDescription></div>
            <LoadingButton
              variant="outline"
              size="sm"
              :loading="table.exporting"
              loading-text="导出中…"
              :disabled="loading || refreshing || previewLoading || forwardLoading || !table.sortedItems.length"
              :data-testid="`${table.kind}-export-excel`"
              @click="exportRanking(table)"
            >
              导出 Excel
            </LoadingButton>
            <div
              v-if="table.kind === 'trend'"
              class="flex max-w-full flex-wrap gap-1"
              aria-label="按趋势状态筛选"
              data-testid="trend-state-filter"
            >
              <Button
                v-for="item in stateFilters"
                :key="item.value"
                size="sm"
                :variant="table.filter === item.value ? 'secondary' : 'ghost'"
                :aria-pressed="table.filter === item.value"
                @click="table.filter = item.value"
              >
                {{ item.label }}
              </Button>
            </div>
            <div
              v-if="table.kind === 'box'"
              class="flex gap-1"
              data-testid="box-state-filter"
              aria-label="按箱体状态筛选"
            >
              <Button
                v-for="item in boxFilters"
                :key="item.value"
                size="sm"
                :variant="table.filter === item.value ? 'secondary' : 'ghost'"
                :aria-pressed="table.filter === item.value"
                @click="table.filter = item.value"
              >
                {{ item.label }}
              </Button>
            </div>
            <p
              v-if="table.kind === 'box'"
              class="w-full text-xs text-muted-foreground"
            >
              独立结构研究信号，不参与 Alpha / Entry。默认显示刚突破与待突破；旧快照需重算后才有箱体结果。
            </p>
            <div
              v-if="table.kind === 'mr'"
              data-testid="mr-state-filter"
              class="flex gap-1"
            >
              <Button
                v-for="item in mrFilters"
                :key="item.value"
                :variant="table.filter === item.value ? 'secondary' : 'ghost'"
                @click="table.filter = item.value"
              >
                {{ item.label }}
              </Button>
            </div>
            <label class="flex items-center gap-2 text-sm text-muted-foreground">搜索
              <input
                v-model="table.search"
                type="search"
                :aria-label="`按名称或代码搜索${table.title}股票`"
                placeholder="股票名称或代码"
                class="h-9 w-56 rounded-md border bg-background px-3 text-foreground"
                :data-testid="`${table.kind}-ranking-search`"
              >
            </label>
            <label class="flex items-center gap-2 text-sm text-muted-foreground">排序指标
              <select
                v-model="table.sortKey"
                :aria-label="`${table.title}排序指标`"
                class="h-9 rounded-md border bg-background px-2 text-foreground"
              >
                <option
                  v-for="column in table.columns"
                  :key="column.key"
                  :value="column.key"
                >{{ metricLabel(column.label).zh }}</option>
              </select>
            </label>
          </CardHeader>
          <CardContent class="px-0">
            <p
              v-if="table.kind !== 'mr' && forwardLoading"
              class="p-2 text-xs text-muted-foreground"
              role="status"
            >
              未来收益率加载中…
            </p>
            <AppApiErrorAlert
              v-if="table.kind !== 'mr' && forwardError"
              :error="forwardError"
              action-label="重试收益率"
              @action="retryForward"
            />
            <Empty v-if="!loading && !items.length">
              <EmptyHeader><EmptyTitle>暂无趋势快照</EmptyTitle><EmptyDescription>请确认所选日期已完成收盘行情同步和策略计算。</EmptyDescription></EmptyHeader>
            </Empty>
            <div
              v-else
              :ref="element => { table.viewport = element as HTMLElement | null; }"
              :class="table.kind === 'trend' ? 'max-h-[60vh]' : 'max-h-[32rem]'"
              class="w-full overflow-auto [&_[data-slot=table-container]]:overflow-visible"
              :data-testid="`${table.kind}-ranking-scroll`"
              tabindex="0"
              aria-label="完整趋势排名，滚动查看全部股票"
              @scroll="table.scrollTop = ($event.target as HTMLElement).scrollTop"
            >
              <Table
                class="w-full"
                :aria-rowcount="table.sortedItems.length + 2"
              >
                <TableHeader class="sticky top-0 z-30 bg-background">
                  <TableRow>
                    <th
                      v-for="group in table.groups"
                      :key="group.label"
                      :colspan="group.count"
                      class="border-r px-4 py-2 text-left text-xs text-muted-foreground"
                    >
                      {{ group.label }}
                    </th>
                  </TableRow>
                  <TableRow>
                    <SortableTableHeader
                      v-for="column in table.columns"
                      :key="column.key"
                      :label="column.label"
                      class="min-w-32 whitespace-nowrap"
                      :class="column.key === 'name' ? 'sticky left-0 z-20 min-w-48 bg-background' : ''"
                      :description="column.description"
                      :active="table.sortKey === column.key"
                      :direction="table.sortDirection"
                      @sort="table.toggleSort(column.key)"
                    />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <tr
                    v-if="table.virtualStart"
                    aria-hidden="true"
                    :style="{ height: `${table.virtualStart * 64}px` }"
                  >
                    <td
                      :colspan="table.columns.length"
                      class="p-0"
                    />
                  </tr>
                  <TableRow
                    v-for="(item, index) in table.renderedRows"
                    :key="item.code"
                    class="cursor-pointer focus-visible:bg-muted/80 focus-visible:outline-none"
                    :data-testid="`${table.kind}-row`"
                    :data-code="item.code"
                    tabindex="0"
                    :aria-rowindex="table.virtualStart + index + 3"
                    :aria-haspopup="'dialog'"
                    :aria-label="`打开 ${item.name} ${item.code} 趋势详情`"
                    :style="table.virtual ? { height: `${64}px` } : undefined"
                    @click="openRankingDetail(item, $event)"
                    @keydown="onRankingRowKeydown(item, $event)"
                  >
                    <TableCell
                      v-for="column in table.columns"
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
                        v-else-if="column.key === 'mrState'"
                        :variant="item.features.mrState === 'MR_REBOUND' ? 'success' : 'warning'"
                      >
                        {{ mrText(item.features.mrState) }}
                      </Badge>
                      <Badge
                        v-else-if="column.key === 'boxState'"
                        :variant="item.features.boxState === 'BOX_BREAKOUT' ? 'success' : item.features.boxState === 'BOX_READY' ? 'info' : 'outline'"
                      >
                        {{ boxStateText(item.features.boxState) }}
                      </Badge>
                      <Badge
                        v-else-if="column.key === 'state'"
                        :variant="badgeVariant(item.state)"
                      >
                        <BilingualEnum
                          :value="item.state"
                          size="badge"
                        />
                      </Badge>
                      <template v-else-if="column.key === 'trendLifecycle'">
                        <BilingualEnum
                          :value="item.trendLifecycle"
                          size="badge"
                        /><span class="block text-xs text-muted-foreground">{{ item.trendDurationDays == null ? '—' : `${item.trendDurationDays}D` }}</span>
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
                        {{ score(item.alphaScore) }}<span class="block text-xs font-normal text-muted-foreground">{{ alphaVersionLabel(item.features.alphaVersion as number | null | undefined) }}</span>
                      </template>
                      <template v-else>
                        {{ rankingCell(item, column) }}
                      </template>
                    </TableCell>
                  </TableRow>
                  <tr
                    v-if="table.bottomSpace"
                    aria-hidden="true"
                    :style="{ height: `${table.bottomSpace}px` }"
                  >
                    <td
                      :colspan="table.columns.length"
                      class="p-0"
                    />
                  </tr>
                </TableBody>
              </Table>
            </div>
            <p
              v-if="items.length && !table.sortedItems.length"
              class="px-6 pt-4 text-sm text-muted-foreground"
              role="status"
            >
              没有匹配的股票，请尝试其他名称、代码或 State 筛选。
            </p>
            <p
              v-if="items.length"
              class="px-6 pt-4 text-sm text-muted-foreground"
              :data-testid="`${table.kind}-ranking-count`"
            >
              显示 {{ table.sortedItems.length }} / {{ items.length }} 条
            </p>
          </CardContent>
        </Card>
      </template>
    </div>

    <section
      id="section-study"
      class="space-y-3"
    >
      <h2 class="text-xl font-semibold">
        历史策略研究
      </h2>
      <p class="text-sm text-muted-foreground">
        比较四类事件在未来 5/10/20D 的事后表现，仅用于研究，不代表实际成交收益。
      </p>
      <TrendEventStudy
        v-if="dataMode === 'official' && studyContextReady && (selectedDate || summary.tradeDate)"
        :market="market"
        :end-date="selectedDate || summary.tradeDate"
      />
      <p
        v-else-if="dataMode === 'preview'"
        data-testid="study-preview-disabled"
        class="text-sm text-muted-foreground"
      >
        历史策略研究仅基于 Official 正式快照。
      </p>
    </section>

    <Dialog
      :open="detailOpen"
      @update:open="onDetailOpenChange"
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
              <BilingualEnum
                :value="detail.latest.state"
                size="badge"
              />
            </Badge><Badge variant="outline">
              {{ detail.latest.setup }}
            </Badge>
          </div>
          <div class="grid grid-cols-1 gap-3 rounded-lg border p-4 text-sm sm:grid-cols-3">
            <div><BilingualLabel
              label="trendDuration"
            /><strong class="mt-1 block">{{ detail.latest.trendDurationDays == null ? '—' : `${detail.latest.trendDurationDays}D` }}</strong></div>
            <div><BilingualLabel
              label="lifecycle"
            /><strong class="mt-1 block"><BilingualEnum
              :value="detail.latest.trendLifecycle"
              size="badge"
            /></strong></div>
            <div><BilingualLabel
              label="fragility"
            /><strong class="mt-1 block">{{ score(detail.latest.fragilityScore) }} / 100</strong></div>
            <div><BilingualLabel
              label="acceleration"
            /><strong class="mt-1 block">{{ score(detail.latest.features.trendAcceleration) }}</strong></div>
            <div><BilingualLabel
              zh="符号效率"
              en="Signed Efficiency"
            /><strong class="mt-1 block">{{ score(detail.latest.features.signedEfficiencyRatio10D) }}</strong></div>
          </div>
          <section
            class="space-y-3 rounded-lg border p-4 text-sm"
            data-testid="trend-risk-sizing"
            aria-label="风险仓位建议"
          >
            <h3 class="font-semibold">
              风险仓位建议
            </h3>
            <template v-if="detail.latest.features.riskSizing">
              <dl class="grid grid-cols-2 gap-3 tabular-nums sm:grid-cols-4">
                <div>
                  <dt>
                    <IndicatorLabel
                      label="建议仓位"
                      :description="descriptions.riskPosition"
                    />
                  </dt>
                  <dd class="font-semibold">
                    {{ pct(detail.latest.features.riskSizing.suggestedPositionPct) }}
                  </dd>
                </div>
                <div>
                  <dt>
                    <IndicatorLabel
                      label="建议止损"
                      :description="descriptions.riskStop"
                    />
                  </dt>
                  <dd class="font-semibold">
                    {{ pct(-detail.latest.features.riskSizing.stopLossPct) }}
                  </dd>
                </div>
                <div>
                  <dt>止损价格</dt>
                  <dd class="font-semibold">
                    {{ price(detail.latest.features.riskSizing.stopPrice) }}
                  </dd>
                </div>
                <div>
                  <dt>账户风险预算</dt>
                  <dd class="font-semibold">
                    {{ pct(detail.latest.features.riskSizing.riskBudgetPct) }}
                  </dd>
                </div>
              </dl>
              <p class="text-xs text-muted-foreground">
                {{ detail.latest.features.riskSizing.atrMultiple }} ATR · {{ detail.latest.features.riskSizing.stopBasis === 'STRUCTURE' ? '10D 结构主导' : 'ATR 主导' }}
              </p>
              <p class="text-xs text-muted-foreground">
                仓位表示按账户净值计算的风险仓位上限，不代表当前 Entry 信号。
              </p>
              <p
                v-if="detail.latest.entryType === 'NONE'"
                class="text-xs text-muted-foreground"
              >
                当前无有效 Entry；仓位仅表示若执行交易时的风险上限。
              </p>
            </template>
            <p
              v-else
              class="text-muted-foreground"
            >
              此快照暂无风险建议。
            </p>
            <p
              v-if="detailMode === 'preview'"
              class="text-xs text-muted-foreground"
            >
              盘中建议基于当前临时日线，ATR 与建议止损/仓位在收盘前可能变化。
            </p>
          </section>
          <section
            class="space-y-3 rounded-lg border p-4 text-sm"
            data-testid="trend-box-structure"
          >
            <h3 class="font-semibold">
              箱体结构 / Box Structure
            </h3>
            <p>{{ boxStateText(detail.latest.features.boxState) }} · {{ detail.latest.features.boxStartDate ?? '—' }} → {{ detail.latest.features.boxEndDate ?? '—' }}</p>
            <p>本次新突破：{{ detail.latest.features.boxBreakoutFresh == null ? '—' : detail.latest.features.boxBreakoutFresh ? '是' : '否' }} · 昨日已确认突破：{{ detail.latest.features.boxPriorBreakoutConfirmed == null ? '—' : detail.latest.features.boxPriorBreakoutConfirmed ? '是' : '否' }}</p>
            <p>箱体事件已触发：{{ detail.latest.features.boxEpisodeConsumed == null ? '—' : detail.latest.features.boxEpisodeConsumed ? '是' : '否' }} · 突破日期：{{ detail.latest.features.boxEpisodeBreakoutDate ?? '—' }}</p>
            <dl class="grid grid-cols-1 gap-3 tabular-nums sm:grid-cols-3">
              <div
                v-for="[key, label, format] in boxDetailFields"
                :key="key"
              >
                <dt>{{ label }}</dt><dd class="font-semibold">
                  {{ boxDetailValue(key, format) }}
                </dd>
              </div>
            </dl>
            <p class="text-xs text-muted-foreground">
              箱体与 ATR 基准截至前一交易日；今日仅判断位置与突破。独立研究信号，尚未完成远期收益校准。
            </p>
          </section>
          <section
            class="space-y-3 rounded-lg border p-4 text-sm"
            data-testid="trend-mr-detail"
          >
            <h3 class="font-semibold">
              超跌反弹 / Mean Reversion
            </h3>
            <p>{{ mrText(detail.latest.features.mrState) }} · Quality {{ score(detail.latest.features.mrQuality) }}</p>
            <p>RSI14 {{ score(detail.latest.features.rsi14) }} · 距 MA20 / ATR {{ score(detail.latest.features.distanceFromMa20Atr) }}</p>
            <p>Oversold {{ score(detail.latest.features.mrOversoldQuality) }} · Distance {{ score(detail.latest.features.mrDistanceQuality) }} · Shock {{ score(detail.latest.features.mrShockQuality) }} · Reversal {{ score(detail.latest.features.mrReversalQuality) }}</p>
            <p class="text-muted-foreground">
              先超跌再确认反弹；同一次超跌过程只触发一次。独立研究信号，不改变 Entry。
            </p>
          </section>
          <DailyKLineCard
            :symbol="detail.latest.code"
            :highlight-date="detail.latest.tradeDate"
          />
          <details class="rounded-lg border p-4 text-sm">
            <summary class="cursor-pointer">
              <BilingualLabel label="fragilityBreakdown" />
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
            <div>Alpha {{ alphaVersionLabel(detail.latest.features.alphaVersion) }}<strong class="block">{{ score(detail.latest.alphaScore) }}</strong></div>
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
                /><strong class="block">{{ detail.latest.features.volumeProvisional ? '盘中原始量比（非全天估算）' : '正式量比' }} {{ score(detail.latest.features.volumeRatio) }} / {{ detail.latest.features.priorCompression ? '是' : '否' }}</strong>
              </div>
            </div>
          </section>
          <section>
            <h3 class="mb-2 font-semibold">
              Entry 买点研究
            </h3>
            <p>{{ detail.latest.entryType ?? '—' }} · {{ score(detail.latest.entryScore) }}</p>
            <p class="text-sm text-muted-foreground">
              {{ descriptions.entry }}
            </p>
            <p v-if="!entryBranches.length">
              —
            </p>
            <div
              v-for="branch in entryBranches"
              :key="branch.label"
              class="mt-3 rounded border p-3 text-sm"
            >
              <strong>{{ branch.label }} · {{ score(branch.data.score) }}</strong>
              <p>连续质量分 {{ score(branch.data.qualityScore) }}；条件未全部通过时 Entry 为 0。</p>
              <div
                v-for="(value, key) in branch.data.components"
                :key="key"
                class="flex justify-between gap-3"
              >
                <span>{{ entryComponentLabels[key] ?? key }}</span>
                <span>{{ score(value) }} × {{ pct(branch.data.normalizedWeights[key]) }} = {{ score(branch.data.contributions[key]) }}</span>
              </div>
              <p class="mt-2 text-muted-foreground">
                {{ Object.entries(branch.data.checks).map(([key, pass]) => `${entryCheckLabels[key] ?? key}: ${pass ? '通过' : '未通过'}`).join(' · ') }}
              </p>
            </div>
          </section>
          <section>
            <IndicatorLabel
              label="ATR"
              :description="descriptions.atr"
              wrap
            />
            <strong class="block">{{ price(detail.latest.atr) }}</strong>
            <p>ATR % {{ pct(detail.latest.features.atrPercent) }} · CLV {{ score(detail.latest.features.closeLocationValue) }}</p>
            <p
              v-if="detail.latest.features.volumeProvisional"
              class="text-sm text-muted-foreground"
            >
              盘中估算量比不可用；Volume Quality 暂定，Entry 排除成交量项。
            </p>
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
