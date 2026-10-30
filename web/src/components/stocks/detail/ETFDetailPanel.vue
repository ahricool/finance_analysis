<script setup lang="ts">
import { formatRank } from '@/utils/rank';
import { formatFixed, formatPercent } from '@/utils/number';
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import BilingualEnum from '@/components/app/BilingualEnum.vue';
import BilingualLabel from '@/components/app/BilingualLabel.vue';
import IndicatorLabel from '@/components/app/IndicatorHelpLabel.vue';
import { Skeleton } from '@/components/ui/skeleton';
import { detailChartHistory as buildDetailChartHistory } from '@/utils/detailChartHistory';
import { formatMarketCurrencyAmount } from '@/utils/marketCurrency';
import type { StockDetailPanelProps } from './types';
import { etfRotationApi } from '@/api/etfRotation';
import type { ETFDetailResponse } from '@/types/etfRotation';
import { indicatorDescriptions as descriptions } from '@/components/etf-rotation/indicatorDescriptions';
import ETFRotationHistoryCharts from '@/components/etf-rotation/ETFRotationHistoryCharts.vue';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

const props = defineProps<StockDetailPanelProps>();
const selected = ref<ETFDetailResponse | null>(null);
const detailLoading = ref(false);
const detailError = ref<ParsedApiError | null>(null);
const unavailable = ref('');
const historyLoading = ref(false);
const historyError = ref<ParsedApiError | null>(null);
const detailMode = computed(() => props.context?.view ?? 'official');
const detailChartHistory = computed(() => selected.value
  ? buildDetailChartHistory(selected.value.history, selected.value.latest, detailMode.value === 'preview') : []);
let generation = 0;
let historyGeneration = 0;

async function loadDetailHistory() {
  const current = selected.value;
  if (!current || detailMode.value !== 'preview') return;
  const request = ++historyGeneration;
  const detailRequest = generation;
  historyLoading.value = true;
  historyError.value = null;
  try {
    const response = await etfRotationApi.detailHistory(current.latest.code, current.market, current.latest.tradeDate);
    if (request === historyGeneration && detailRequest === generation && selected.value === current) {
      current.history = response.history.filter(row => row.tradeDate < current.latest.tradeDate);
    }
  } catch (reason) {
    if (request === historyGeneration && detailRequest === generation) historyError.value = getParsedApiError(reason);
  } finally {
    if (request === historyGeneration && detailRequest === generation) historyLoading.value = false;
  }
}
async function loadDetail() {
  const request = ++generation;
  ++historyGeneration;
  selected.value = null;
  detailError.value = null;
  historyError.value = null;
  historyLoading.value = false;
  detailLoading.value = false;
  unavailable.value = '';
  const { symbol, market } = props;
  const tradeDate = props.context?.tradeDate;
  const preview = detailMode.value === 'preview';
  if (market !== 'CN' && market !== 'US') {
    unavailable.value = '当前市场暂不支持ETF 轮动。';
    return;
  }
  if (!symbol) { unavailable.value = '请选择证券以查看ETF 轮动。'; return; }
  detailLoading.value = true;
  try {
    if (preview) {
      const response = await etfRotationApi.previewDetail(symbol, market, tradeDate);
      if (request !== generation) return;
      selected.value = response;
      void loadDetailHistory();
    } else {
      const response = await etfRotationApi.detail(symbol, market, 60, tradeDate);
      if (request === generation) selected.value = response;
    }
  } catch (reason) {
    if (request !== generation) return;
    const parsed = getParsedApiError(reason);
    if (parsed.status === 404) unavailable.value = preview ? '此证券在所选日期暂无ETF 轮动预演数据。' : '此证券在所选日期暂无ETF 轮动数据。';
    else detailError.value = parsed;
  } finally {
    if (request === generation) detailLoading.value = false;
  }
}
watch([() => props.symbol, () => props.market, () => props.context?.tradeDate, () => props.context?.view], loadDetail, { immediate: true });
onBeforeUnmount(() => { ++generation; ++historyGeneration; });
function pct(value: number | null | undefined, signed = true) { return formatPercent(value, { digits: 2, signed }); }
function score(value: number | null | undefined) { return formatFixed(value, { digits: 1 }); }
function decimal(value: number | null | undefined, digits = 3) { return value == null ? '—' : value.toFixed(digits); }
function price(value: number | null) { return formatMarketCurrencyAmount(value, props.market); }
function rankChange(value: number | null) { return value == null ? '—' : `${value > 0 ? '+' : ''}${value}`; }
function boolText(value: boolean | null) { return value == null ? '—' : value ? '通过' : '未通过'; }
</script>

<template>
  <section
    class="min-w-0 space-y-5"
    data-testid="etf-detail-modal"
  >
    <p
      v-if="selected"
      class="text-sm text-muted-foreground"
    >
      {{ selected.metadata.category }} / {{ selected.metadata.theme }} · {{ selected.metadata.riskGroup }} · {{ selected.latest.tradeDate }}
    </p>
    <AppApiErrorAlert
      v-if="detailError"
      :error="detailError"
      action-label="重试"
      @action="loadDetail"
    /><Skeleton
      v-else-if="detailLoading"
      class="h-48"
    />
    <p
      v-else-if="unavailable"
      class="text-sm text-muted-foreground"
      data-testid="etf-detail-unavailable"
    >
      {{ unavailable }}
    </p>
    <template v-else-if="selected">
      <p class="text-sm font-medium">
        排名 {{ formatRank(selected.latest.rank, selected.latest.rankTotal) }}
      </p>
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
      <div
        data-testid="etf-factor-grid"
        class="grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-3"
      >
        <div
          v-for="factor in ([['entry',selected.latest.entryScore,descriptions.entry],['composite',selected.latest.compositeScore,descriptions.composite],['momentum',selected.latest.momentumStrengthScore,descriptions.momentum],['relativeStrength',selected.latest.relativeStrengthScore,descriptions.relativeStrength],['acceleration',selected.latest.accelerationScore,descriptions.acceleration],['trendQuality',selected.latest.trendQualityScore,descriptions.trendQuality],['efficiency',selected.latest.efficiencyScore,descriptions.efficiency]] as const)"
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
        <CardHeader><CardTitle><BilingualLabel label="rawMetrics" /></CardTitle></CardHeader><CardContent
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
        <CardHeader><CardTitle><BilingualLabel label="eligibilitySignal" /></CardTitle></CardHeader><CardContent class="grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-3">
          <div>
            <IndicatorLabel
              label="绝对趋势"
              en="Absolute Trend"
              :description="descriptions.absoluteTrend"
              wrap
            /><strong class="block">{{ boolText(selected.latest.absoluteTrendEligible) }}</strong>
          </div>
          <div>
            <IndicatorLabel
              label="流动性"
              en="Liquidity"
              :description="descriptions.liquidity"
              wrap
            /><strong class="block">{{ boolText(selected.latest.liquidityEligible) }}</strong>
          </div>
          <div>
            <IndicatorLabel
              label="state"
              :description="descriptions.state"
              wrap
            /><strong class="block"><BilingualEnum
              :value="selected.latest.state"
              size="badge"
            /></strong>
          </div>
          <div>
            <IndicatorLabel
              label="action"
              :description="descriptions.action"
              wrap
            /><strong class="block"><BilingualEnum
              :value="selected.latest.action"
              size="badge"
            /></strong>
          </div>
        </CardContent>
      </Card>
      <Card
        data-testid="etf-detail-history"
      >
        <CardHeader><CardTitle><BilingualLabel label="history" /></CardTitle><CardDescription>价格/MA、综合分、排名与相对强弱；旧快照缺失字段时保留空点。</CardDescription></CardHeader><CardContent><ETFRotationHistoryCharts :history="detailChartHistory" /></CardContent>
      </Card>
    </template>
  </section>
</template>
