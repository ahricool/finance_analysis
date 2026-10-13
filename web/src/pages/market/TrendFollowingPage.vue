<script setup lang="ts">
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
import type { StockDetailContext } from '@/components/stocks/detail/types';
import PageHeader from '@/components/layout/PageHeader.vue';
import TrendEventStudy from '@/components/trend-following/TrendEventStudy.vue';
import { alphaVersionLabel } from '@/utils/trendFollowing';
import { exportExcel, type ExcelColumn } from '@/utils/excelExport';
import { forwardReturnColumns, useForwardReturns } from '@/composables/useForwardReturns';
import { parseDate } from '@internationalized/date';
import ResearchMarketToggle from '@/components/research/ResearchMarketToggle.vue';
import { useRoute } from 'vue-router';
import { useLazyResearchPreview } from '@/composables/useLazyResearchPreview';
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue';
import { RefreshCcw } from 'lucide-vue-next';
import { toast } from 'vue-sonner';
import { trendFollowingApi } from '@/api/trendFollowing';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import BilingualEnum from '@/components/app/BilingualEnum.vue';
import IndicatorLabel from '@/components/app/IndicatorHelpLabel.vue';
import { metricLabel } from '@/i18n/labels';
import LoadingButton from '@/components/app/LoadingButton.vue';
import ResearchDataModeToggle from '@/components/research/ResearchDataModeToggle.vue';
import ResearchDataStatusBar from '@/components/research/ResearchDataStatusBar.vue';
import { trendIndicatorDescriptions, trendPeriodText } from '@/components/trend-following/indicatorDescriptions';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import TrendMarketOverview from '@/components/trend-following/TrendMarketOverview.vue';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
import type {
  TrendMarket,
  TrendPeriod,
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
const trendPeriod = ref<TrendPeriod>(20);
const periodText = (text: string) => trendPeriodText(text, trendPeriod.value);
const descriptions = new Proxy(trendIndicatorDescriptions, { get: (target, key: string) => target[key] == null ? undefined : periodText(target[key]) });
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
  useLazyResearchPreview<TrendMarket, TrendPreviewStatusResponse, TrendPreviewResponse>(() => market.value, {
    previewStatus: market => trendFollowingApi.previewStatus(market, trendPeriod.value),
    preview: market => trendFollowingApi.preview(market, trendPeriod.value),
  });
const previewInfo = computed(() => previewPayload.value ?? previewStatus.value);
const officialLatest = shallowRef<TrendRankingResponse | null>(null);
const officialSelected = shallowRef<TrendRankingResponse | null>(null);
const detailOpen = ref(false);
const detailStock = ref<{ code: string; name: string; market_type: TrendMarket } | null>(null);
const detailContext = ref<StockDetailContext>({});
const rankingDetailTrigger = ref<{ code: string; el: HTMLElement | null } | null>(null);
const trendColumns = [
  { key: 'rank', label: 'alphaRank', group: 'Core', format: 'number', description: trendIndicatorDescriptions.rank },
  { key: 'name', label: '股票名称', group: 'Core', format: 'text', description: undefined },
  { key: 'state', label: 'state', group: 'Core', format: 'text', description: trendIndicatorDescriptions.state },
  { key: 'alphaScore', label: 'alphaScore', group: 'Core', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'entryScore', label: 'entryScore', group: 'Core', format: 'score', description: trendIndicatorDescriptions.entry },
  { key: 'entryType', label: 'entryType', group: 'Core', format: 'text', description: trendIndicatorDescriptions.entry },
  { key: 'trendScore', label: 'trendScore', group: 'Core', format: 'score', description: trendIndicatorDescriptions.trend },
  { key: 'rsScore', label: 'rsScore', group: 'Core', format: 'score', description: trendIndicatorDescriptions.relativeStrength },
  { key: 'setupScore', label: 'setupScore', group: 'Core', format: 'score', description: trendIndicatorDescriptions.breakout },
  { key: 'pathScore', label: 'pathScore', group: 'Core', format: 'score', description: trendIndicatorDescriptions.path },
  { key: 'distanceFromMa20', label: 'distanceFromMa20', group: 'Core', format: 'percent', description: trendIndicatorDescriptions.distanceFromMa20 },
  { key: 'atrPercent', label: 'atrPercent', group: 'Core', format: 'percent', description: trendIndicatorDescriptions.atrPercent },
  { key: 'fragilityScore', label: 'fragility', group: 'Core', format: 'score', description: trendIndicatorDescriptions.fragility },
  { key: 'closeLocationValue', label: 'clv', group: 'Core', format: 'ratio', description: trendIndicatorDescriptions.clv },
  ...forwardReturnColumns,
  { key: 'trendLifecycle', label: 'lifecycleAge', group: 'Core', format: 'number', description: trendIndicatorDescriptions.lifecycle },
  { key: 'rankChange5D', label: '排名趋势', group: 'Core', format: 'number', description: trendIndicatorDescriptions.rankChange },
  { key: 'referencePrice', label: 'referencePrice', group: 'Core', format: 'price', description: trendIndicatorDescriptions.reference },
  { key: 'alphaTrendContribution', label: 'Trend Contribution', group: 'Alpha', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'alphaRsContribution', label: 'RS Contribution', group: 'Alpha', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'alphaSetupContribution', label: 'Setup Contribution', group: 'Alpha', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'alphaPathContribution', label: 'Path Contribution', group: 'Alpha', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'weightedSlopePercentile', label: 'Slope Percentile 20D', group: 'Trend', format: 'score', description: trendIndicatorDescriptions.slopePercentile },
  { key: 'r2Quality', label: 'R² Quality', group: 'Trend', format: 'score', description: trendIndicatorDescriptions.r2Quality },
  { key: 'momentumQuality', label: 'Momentum Quality', group: 'Trend', format: 'score', description: trendIndicatorDescriptions.momentumQuality },
  { key: 'return10DQuality', label: 'Return 10D Quality', group: 'Trend', format: 'score', description: trendIndicatorDescriptions.returnQuality },
  { key: 'return20DQuality', label: 'Return 20D Quality', group: 'Trend', format: 'score', description: trendIndicatorDescriptions.returnQuality },
  { key: 'drawdownQuality', label: 'Drawdown Quality', group: 'Trend', format: 'score', description: trendIndicatorDescriptions.drawdownQuality },
  { key: 'rs5DQuality', label: 'RS 5D Quality', group: 'RS', format: 'score', description: trendIndicatorDescriptions.rsQuality },
  { key: 'rs10DQuality', label: 'RS 10D Quality', group: 'RS', format: 'score', description: trendIndicatorDescriptions.rsQuality },
  { key: 'rs20DQuality', label: 'RS 20D Quality', group: 'RS', format: 'score', description: trendIndicatorDescriptions.rsQuality },
  { key: 'breakoutQuality', label: 'Breakout Quality', group: 'Setup', format: 'score', description: trendIndicatorDescriptions.breakout },
  { key: 'extensionQuality', label: 'Extension Quality', group: 'Setup', format: 'score', description: trendIndicatorDescriptions.breakout },
  { key: 'volumeQuality', label: 'Volume Quality', group: 'Setup', format: 'score', description: trendIndicatorDescriptions.breakout },
  { key: 'compressionQuality', label: 'Compression Quality', group: 'Setup', format: 'score', description: trendIndicatorDescriptions.breakout },
  { key: 'concentrationQuality', label: 'Concentration Quality', group: 'Path', format: 'score', description: trendIndicatorDescriptions.concentration },
  { key: 'volatilityQuality', label: 'Volatility Quality', group: 'Path', format: 'score', description: trendIndicatorDescriptions.expansion },
  { key: 'downsideControlQuality', label: 'Downside Control Quality', group: 'Path', format: 'score', description: trendIndicatorDescriptions.downside },
  { key: 'setup', label: 'Setup', group: 'Signals / Explain', format: 'text', description: trendIndicatorDescriptions.setup },
  { key: 'trendCandidate', label: 'Trend Candidate', group: 'Signals / Explain', format: 'boolean', description: trendIndicatorDescriptions.candidate },
  { key: 'priorCompression', label: 'Prior Compression', group: 'Signals / Explain', format: 'boolean', description: trendIndicatorDescriptions.volumeCompression },
  { key: 'compressionBreakout', label: 'Compression Breakout', group: 'Signals / Explain', format: 'boolean', description: trendIndicatorDescriptions.setup },
  { key: 'trendResume', label: 'Trend Resume', group: 'Signals / Explain', format: 'boolean', description: trendIndicatorDescriptions.trendResume },
  { key: 'signedEfficiencyRatio10D', label: 'Signed Efficiency 10D', group: 'Signals / Explain', format: 'score', description: trendIndicatorDescriptions.signedEfficiency },
  { key: 'rawWeightedSlope', label: 'Weighted Slope 20D', group: 'Signals / Explain', format: 'slope', description: trendIndicatorDescriptions.weightedSlope },
  { key: 'weightedR2', label: 'Weighted R²', group: 'Signals / Explain', format: 'r2', description: trendIndicatorDescriptions.r2 },
  { key: 'return5D', label: '5D Return', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.return },
  { key: 'return10D', label: '10D Return', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.return },
  { key: 'return20D', label: '20D Return', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.return },
  { key: 'drawdown20D', label: 'Drawdown 20D', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.drawdown },
  { key: 'rs5D', label: 'RS 5D', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.rawRelativeStrength },
  { key: 'rs10D', label: 'RS 10D', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.rawRelativeStrength },
  { key: 'rs20D', label: 'RS 20D', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.rawRelativeStrength },
  { key: 'volumeRatio', label: 'Volume Ratio', group: 'Signals / Explain', format: 'score', description: trendIndicatorDescriptions.volumeCompression },
  { key: 'positiveReturnConcentration', label: 'Return Concentration', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.concentration },
  { key: 'atrExpansionRatio', label: 'ATR Expansion', group: 'Signals / Explain', format: 'ratio', description: trendIndicatorDescriptions.expansion },
  { key: 'downsideUpsideRatio', label: 'Downside / Upside', group: 'Signals / Explain', format: 'ratio', description: trendIndicatorDescriptions.downside },
  { key: 'ma10', label: 'MA10', group: 'Signals / Explain', format: 'score', description: trendIndicatorDescriptions.movingAverage },
  { key: 'ma20', label: 'MA20', group: 'Signals / Explain', format: 'score', description: trendIndicatorDescriptions.movingAverage },
  { key: 'ma10Slope', label: 'MA10 Slope', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.maSlope },
  { key: 'ma20Slope', label: 'MA20 Slope', group: 'Signals / Explain', format: 'percent', description: trendIndicatorDescriptions.maSlope },
  { key: 'trendAcceleration', label: 'Trend Acceleration', group: 'Risk / Health', format: 'score', description: trendIndicatorDescriptions.trendAcceleration },
] as const;
const boxColumns = [
  { key: 'name', label: '股票名称', format: 'text' },
  { key: 'boxState', label: '状态', format: 'text', description: trendIndicatorDescriptions.boxState },
  { key: 'boxQuality', label: 'boxQuality', format: 'score', description: trendIndicatorDescriptions.boxQuality },
  { key: 'boxWindowDays', label: 'boxDays', format: 'number', description: trendIndicatorDescriptions.boxWindowDays },
  { key: 'boxWidthPct', label: 'boxWidth', format: 'percent', description: trendIndicatorDescriptions.boxWidthPct },
  { key: 'distanceToBoxHighPct', label: '距箱顶', format: 'percent', description: trendIndicatorDescriptions.distanceToBoxHighPct },
  { key: 'boxBreakoutDistanceAtr', label: '突破距离', format: 'ratio', description: trendIndicatorDescriptions.boxBreakoutDistanceAtr },
  { key: 'boxUpperTouches', label: '上沿测试', format: 'number', description: trendIndicatorDescriptions.boxUpperTouches },
  { key: 'rsScore', label: 'rsScore', format: 'score', description: trendIndicatorDescriptions.relativeStrength },
  { key: 'trendScore', label: 'trendScore', format: 'score', description: trendIndicatorDescriptions.trend },
  { key: 'alphaScore', label: 'alpha', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'volumeRatio', label: 'volume', format: 'ratio', description: trendIndicatorDescriptions.volumeCompression },
  ...forwardReturnColumns,
] as const;
const mrColumns = [
  { key: 'name', label: '股票名称', format: 'text' },
  { key: 'mrState', label: 'mrState', format: 'text', description: trendIndicatorDescriptions.mrState },
  { key: 'mrQuality', label: 'mrQuality', format: 'score', description: trendIndicatorDescriptions.mrQuality },
  { key: 'rsi14', label: 'RSI20', format: 'score', description: trendIndicatorDescriptions.rsi14 },
  { key: 'distanceFromMa20Atr', label: '距 MA20 / ATR', format: 'ratio', description: trendIndicatorDescriptions.distanceFromMa20Atr },
  { key: 'return3D', label: 'return3D', format: 'percent', description: trendIndicatorDescriptions.return },
  { key: 'return5D', label: 'return5D', format: 'percent', description: trendIndicatorDescriptions.return },
  { key: 'closeLocationValue', label: 'clv', format: 'ratio', description: trendIndicatorDescriptions.clv },
  { key: 'trendScore', label: 'trendScore', format: 'score', description: trendIndicatorDescriptions.trend },
  { key: 'rsScore', label: 'rsScore', format: 'score', description: trendIndicatorDescriptions.relativeStrength },
  { key: 'alphaScore', label: 'alpha', format: 'score', description: trendIndicatorDescriptions.alpha },
  { key: 'state', label: 'state', format: 'text', description: trendIndicatorDescriptions.state },
] as const;
const mrFilters = [{ value: 'all', label: '全部超跌机会' }, { value: 'MR_REBOUND', label: '反弹确认' }, { value: 'MR_OVERSOLD', label: '超跌观察' }];
const mrText = (value: unknown) => value === 'MR_REBOUND' ? '反弹确认' : value === 'MR_OVERSOLD' ? '超跌观察' : value === 'MR_NONE' ? '无超跌机会' : '—';
const mrPriority = (row: TrendRankingSnapshot) => row.features.mrState === 'MR_REBOUND' ? 0 : row.features.mrState === 'MR_OVERSOLD' ? 1 : 2;
type ColumnSource = typeof trendColumns[number] | typeof boxColumns[number] | typeof mrColumns[number];
type RankingColumn = { key: ColumnSource['key']; label: string; format: ColumnSource['format']; group: string; description?: string };
type SortKey = RankingColumn['key'];
const boxFilters = [
  { value: 'opportunities', label: '全部机会' }, { value: 'BOX_BREAKOUT', label: '刚突破' },
  { value: 'BOX_READY', label: '待突破' }, { value: 'BOX_FORMING', label: '形成中' },
];
function boxStateText(state: unknown) {
  return state === 'BOX_BREAKOUT' ? '刚突破' : state === 'BOX_READY' ? '待突破' : state === 'BOX_FORMING' ? '整理中' : state === 'NONE' ? '无结构机会' : '—';
}
const boxPriority = (item: TrendRankingSnapshot) => item.features.boxState === 'BOX_BREAKOUT' ? 0
  : item.features.boxState === 'BOX_READY' ? 1 : item.features.boxState === 'BOX_FORMING' ? 2 : 3;
function defaultBoxSort(left: TrendRankingSnapshot, right: TrendRankingSnapshot) {
  return boxPriority(left) - boxPriority(right)
    || (right.features.boxQuality ?? -1) - (left.features.boxQuality ?? -1)
    || right.alphaScore - left.alphaScore || left.code.localeCompare(right.code);
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
function columnLabel(column: RankingColumn) {
  const label = metricLabel(column.label).zh;
  const translated = periodText(label);
  return column.key.startsWith('forwardReturn') || translated === label ? column.label : translated;
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
      const zh = metricLabel(columnLabel(column)).zh;
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
    await exportExcel(`${table.kind === 'trend' ? '趋势分析' : table.title}_${market.value}_${trendPeriod.value}日_${summary.value.tradeDate}_${dataMode.value}.xlsx`, '趋势分析', columns, rows);
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
  const searchAll = computed(() => !!search.value.trim()
    && (kind === 'box' && filter.value === 'opportunities' || kind === 'mr' && filter.value === 'all'));
  const filteredItems = computed(() => {
    const query = search.value.trim().toLocaleLowerCase();
    return items.value.filter(item => {
      if (kind === 'box') {
        const state = item.features.boxState;
        if (!searchAll.value && (filter.value === 'opportunities' ? state !== 'BOX_BREAKOUT' && state !== 'BOX_READY' : state !== filter.value)) return false;
      } else if (kind === 'mr') {
        const state = item.features.mrState;
        if (!searchAll.value && (filter.value === 'all' ? state !== 'MR_REBOUND' && state !== 'MR_OVERSOLD' : state !== filter.value)) return false;
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
    searchAll, sortedItems, virtual, virtualStart, renderedRows, bottomSpace, toggleSort,
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
  if (auxiliary) void trendFollowingApi.dates(requestedMarket, trendPeriod.value).then(result => {
    if (current === generation) availableDates.value = result.items;
  }).catch(() => undefined);
  const previewTask = auxiliary ? refreshPreviewStatus(refreshVisiblePreview) : Promise.resolve();
  try {
    const ranking = await trendFollowingApi.ranking(requestedMarket, requestedDate, trendPeriod.value);
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
    const result = await trendFollowingApi.run(market.value, undefined, trendPeriod.value);
    toast.success(`趋势跟踪任务已提交：${result.taskId}`);
  } catch (reason) {
    error.value = getParsedApiError(reason);
  } finally {
    running.value = false;
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
function openDetail(item: Pick<TrendSnapshot, 'code'> & { tradeDate?: string; preview?: boolean }) {
  const row = items.value.find(row => row.code === item.code);
  const view = item.preview === undefined ? dataMode.value : item.preview ? 'preview' : 'official';
  detailStock.value = { code: item.code, name: row?.name ?? item.code, market_type: market.value };
  detailContext.value = {
    view,
    trendPeriod: trendPeriod.value,
    tradeDate: view === 'preview' ? item.tradeDate ?? previewPayload.value?.tradeDate
      : item.preview === undefined ? selectedDate.value || item.tradeDate : item.tradeDate,
  };
  detailOpen.value = true;
}
watch([market, trendPeriod], () => {
  studyContextReady.value = false;
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
    <PageHeader
      variant="section"
      title="趋势跟踪"
      en="Trend Following"
      :description="`${scope} · ${trendPeriod}日策略 · 跟踪股票趋势强弱、排名变化与风险指标，观察趋势延续和转弱。`"
    >
      <template #actions>
        <div
          class="flex items-center gap-1"
          role="group"
          aria-label="趋势周期"
          data-testid="trend-period"
        >
          <Button
            v-for="period in ([20, 40, 60] as const)"
            :key="period"
            :variant="trendPeriod === period ? 'default' : 'outline'"
            size="sm"
            :aria-pressed="trendPeriod === period"
            @click="trendPeriod = period"
          >
            {{ period }}日
          </Button>
        </div>
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
      </template>
    </PageHeader>
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
          class="gap-0 py-2.5! shadow-none"
        >
          <CardContent class="min-w-0 space-y-1 px-3 py-0">
            <IndicatorLabel
              :label="String(card[0])"
              :description="String(card[2])"
              wrap
            />
            <BilingualEnum
              v-if="card[3] === 'enum'"
              :value="String(card[1] ?? '')"
              size="large"
              class="w-full"
            />
            <strong
              v-else
              class="block truncate text-lg tabular-nums"
            >{{ card[1] }}</strong>
          </CardContent>
        </Card>
      </div>



      <TrendMarketOverview
        v-if="!loading && marketOverviewReady"
        :key="`${market}-${trendPeriod}`"
        :trend-period="trendPeriod"
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
                排名 / 分数变动
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
              class="flex max-w-full flex-wrap gap-1"
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
                {{ table.searchAll && item.value === 'opportunities' ? '全部股票' : item.label }}
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
                :aria-pressed="table.filter === item.value"
                @click="table.filter = item.value"
              >
                {{ table.searchAll && item.value === 'all' ? '全部股票' : item.label }}
              </Button>
            </div>
            <p
              v-if="table.kind !== 'trend'"
              class="w-full text-xs text-muted-foreground"
              :data-testid="`${table.kind}-search-scope`"
            >
              {{ table.searchAll ? '正在搜索当前快照全部股票，含未出现机会或缺少指标的股票。' : '默认仅展示机会股票；搜索可查看当前快照全部股票，具体状态筛选仍生效。' }}
            </p>
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
                      :label="columnLabel(column)"
                      class="min-w-32 whitespace-nowrap"
                      :class="column.key === 'name' ? 'sticky left-0 z-20 min-w-48 bg-background' : ''"
                      :description="column.description && column.key !== 'rankChange5D' && !column.key.startsWith('forwardReturn') ? periodText(column.description) : column.description"
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
                        :variant="item.features.mrState === 'MR_REBOUND' ? 'success' : item.features.mrState === 'MR_OVERSOLD' ? 'warning' : 'outline'"
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
        :key="`${market}-${trendPeriod}`"
        :trend-period="trendPeriod"
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

    <StockDetailDialog
      :stock="detailOpen ? detailStock : null"
      kind="research"
      initial-tab="trend"
      :context="detailContext"
      @update:open="onDetailOpenChange"
    />
  </div>
</template>

