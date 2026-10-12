<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import DailyKLineCard from '@/components/market-data/DailyKLineCard.vue';
import BilingualEnum from '@/components/app/BilingualEnum.vue';
import BilingualLabel from '@/components/app/BilingualLabel.vue';
import IndicatorLabel from '@/components/app/IndicatorHelpLabel.vue';
import { Skeleton } from '@/components/ui/skeleton';
import { detailChartHistory as buildDetailChartHistory } from '@/utils/detailChartHistory';
import { formatMarketCurrencyAmount } from '@/utils/marketCurrency';
import { isPreviewCompleted } from '@/utils/researchPreview';
import type { StockDetailPanelProps } from './types';
import { trendFollowingApi } from '@/api/trendFollowing';
import type { TrendAlphaBreakdown, TrendDetailResponse, TrendState } from '@/types/trendFollowing';
import { alphaVersionLabel } from '@/utils/trendFollowing';
import { trendIndicatorDescriptions as descriptions } from '@/components/trend-following/indicatorDescriptions';
import { Badge } from '@/components/ui/badge';
import TrendFragilityHistoryChart from '@/components/trend-following/TrendFragilityHistoryChart.vue';
import TrendRankHistoryChart from '@/components/trend-following/TrendRankHistoryChart.vue';

const props = defineProps<StockDetailPanelProps>();
const detail = ref<TrendDetailResponse | null>(null);
const detailLoading = ref(false);
const detailError = ref<ParsedApiError | null>(null);
const unavailable = ref('');
const historyLoading = ref(false);
const historyError = ref<ParsedApiError | null>(null);
const detailMode = computed(() => props.context?.view ?? 'official');
const detailChartHistory = computed(() => detail.value
  ? buildDetailChartHistory(detail.value.history, detail.value.latest, detailMode.value === 'preview') : []);
let generation = 0;
let historyGeneration = 0;

async function loadDetailHistory() {
  const current = detail.value;
  if (!current || detailMode.value !== 'preview') return;
  const request = ++historyGeneration;
  const detailRequest = generation;
  historyLoading.value = true;
  historyError.value = null;
  try {
    const response = await trendFollowingApi.detailHistory(current.latest.code, current.market, current.latest.tradeDate);
    if (request === historyGeneration && detailRequest === generation && detail.value === current) {
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
  detail.value = null;
  detailError.value = null;
  historyError.value = null;
  historyLoading.value = false;
  detailLoading.value = false;
  unavailable.value = '';
  const { symbol, market } = props;
  const tradeDate = props.context?.tradeDate;
  const preview = detailMode.value === 'preview';
  if (market !== 'CN' && market !== 'US') {
    unavailable.value = '当前市场暂不支持趋势研究。';
    return;
  }
  if (!symbol) { unavailable.value = '请选择证券以查看趋势研究。'; return; }
  detailLoading.value = true;
  try {
    if (preview) {
      const payload = await trendFollowingApi.preview(market);
      if (request !== generation) return;
      const snapshot = payload && isPreviewCompleted(payload.status)
        && (!tradeDate || payload.tradeDate === tradeDate)
        ? payload.snapshots.find(row => row.code === symbol && (!tradeDate || row.tradeDate === tradeDate)) : undefined;
      if (!snapshot || !payload) { unavailable.value = '此证券在所选日期暂无趋势研究预演数据。'; return; }
      detail.value = { market, metadata: { market, code: snapshot.code, name: snapshot.name }, latest: snapshot, history: [], marketContext: { ...payload, generatedAt: payload.previewTime ?? '' } };
      void loadDetailHistory();
    } else {
      const response = await trendFollowingApi.detail(symbol, market, 60, tradeDate);
      if (request === generation) detail.value = response;
    }
  } catch (reason) {
    if (request !== generation) return;
    const parsed = getParsedApiError(reason);
    if (parsed.status === 404) unavailable.value = '此证券在所选日期暂无趋势研究数据。';
    else detailError.value = parsed;
  } finally {
    if (request === generation) detailLoading.value = false;
  }
}
watch([() => props.symbol, () => props.market, () => props.context?.tradeDate, () => props.context?.view], loadDetail, { immediate: true });
onBeforeUnmount(() => { ++generation; ++historyGeneration; });
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
function boxStateText(state: unknown) {
  return state === 'BOX_BREAKOUT' ? '刚突破' : state === 'BOX_READY' ? '待突破' : state === 'BOX_FORMING' ? '整理中' : state === 'NONE' ? '无结构机会' : '—';
}
const mrText = (value: unknown) => value === 'MR_REBOUND' ? '反弹确认' : value === 'MR_OVERSOLD' ? '超跌观察' : value === 'MR_NONE' ? '无超跌机会' : '—';
function score(value: number | null | undefined) { return value == null ? '—' : value.toFixed(1); }
function pct(value: number | null | undefined) { return value == null ? '—' : `${(value * 100).toFixed(1)}%`; }
function price(value: number | null | undefined) {
  return value == null ? '—' : formatMarketCurrencyAmount(value, props.market);
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
</script>

<template>
  <section
    class="min-w-0 space-y-4"
    data-testid="trend-detail"
  >
    <p
      v-if="detail"
      class="text-sm text-muted-foreground"
    >
      {{ detail.metadata.name }} · {{ detail.metadata.code }} · {{ detail.latest.tradeDate }} · 趋势指标、风险与状态历史
    </p>
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
      action-label="重试"
      @action="loadDetail"
    />
    <p
      v-else-if="unavailable"
      class="text-sm text-muted-foreground"
      data-testid="trend-detail-unavailable"
    >
      {{ unavailable }}
    </p>
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
        <div>
          <BilingualLabel
            label="trendDuration"
            :description="descriptions.trendDuration"
          /><strong class="mt-1 block">{{ detail.latest.trendDurationDays == null ? '—' : `${detail.latest.trendDurationDays}D` }}</strong>
        </div>
        <div>
          <BilingualLabel
            label="lifecycle"
            :description="descriptions.lifecycle"
          /><strong class="mt-1 block"><BilingualEnum
            :value="detail.latest.trendLifecycle"
            size="badge"
          /></strong>
        </div>
        <div>
          <BilingualLabel
            label="fragility"
            :description="descriptions.fragility"
          /><strong class="mt-1 block">{{ score(detail.latest.fragilityScore) }} / 100</strong>
        </div>
        <div>
          <BilingualLabel
            label="acceleration"
            :description="descriptions.trendAcceleration"
          /><strong class="mt-1 block">{{ score(detail.latest.features.trendAcceleration) }}</strong>
        </div>
        <div>
          <BilingualLabel
            zh="符号效率"
            :description="descriptions.signedEfficiency"
            en="Signed Efficiency"
          /><strong class="mt-1 block">{{ score(detail.latest.features.signedEfficiencyRatio10D) }}</strong>
        </div>
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
              <dt>
                <IndicatorLabel
                  label="止损价格"
                  :description="descriptions.riskStop"
                  compact
                />
              </dt>
              <dd class="font-semibold">
                {{ price(detail.latest.features.riskSizing.stopPrice) }}
              </dd>
            </div>
            <div>
              <dt>
                <IndicatorLabel
                  label="账户风险预算"
                  :description="descriptions.riskPosition"
                  compact
                />
              </dt>
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
        <p>
          <IndicatorLabel
            label="箱体状态"
            :description="descriptions.boxState"
            compact
          /> {{ boxStateText(detail.latest.features.boxState) }} · {{ detail.latest.features.boxStartDate ?? '—' }} → {{ detail.latest.features.boxEndDate ?? '—' }}
        </p>
        <p>本次新突破：{{ detail.latest.features.boxBreakoutFresh == null ? '—' : detail.latest.features.boxBreakoutFresh ? '是' : '否' }} · 昨日已确认突破：{{ detail.latest.features.boxPriorBreakoutConfirmed == null ? '—' : detail.latest.features.boxPriorBreakoutConfirmed ? '是' : '否' }}</p>
        <p>箱体事件已触发：{{ detail.latest.features.boxEpisodeConsumed == null ? '—' : detail.latest.features.boxEpisodeConsumed ? '是' : '否' }} · 突破日期：{{ detail.latest.features.boxEpisodeBreakoutDate ?? '—' }}</p>
        <dl class="grid grid-cols-1 gap-3 tabular-nums sm:grid-cols-3">
          <div
            v-for="[key, label, format] in boxDetailFields"
            :key="key"
          >
            <dt>
              <IndicatorLabel
                :label="label"
                :description="descriptions[key]"
                compact
              />
            </dt><dd class="font-semibold">
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
        <p>
          <IndicatorLabel
            label="超跌状态"
            :description="descriptions.mrState"
            compact
          /> {{ mrText(detail.latest.features.mrState) }} · <IndicatorLabel
            label="质量"
            :description="descriptions.mrQuality"
            compact
          /> {{ score(detail.latest.features.mrQuality) }}
        </p>
        <p>
          <IndicatorLabel
            label="RSI14"
            :description="descriptions.rsi14"
            compact
          /> {{ score(detail.latest.features.rsi14) }} · <IndicatorLabel
            label="距 MA20 / ATR"
            :description="descriptions.distanceFromMa20Atr"
            compact
          /> {{ score(detail.latest.features.distanceFromMa20Atr) }}
        </p>
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
          <BilingualLabel
            label="fragilityBreakdown"
            :description="descriptions.fragility"
          />
        </summary>
        <p class="my-2 text-xs text-muted-foreground">
          与 3 / 5 个历史正式快照日比较；缺失项不计权重，数据不足不生成总分。
        </p>
        <dl class="grid grid-cols-2 gap-2">
          <div
            v-for="(value, key) in detail.latest.fragilityBreakdown"
            :key="key"
          >
            <dt>
              <IndicatorLabel
                :label="String(key)"
                :description="descriptions[key]"
                compact
              />
            </dt><dd>{{ score(value) }}</dd>
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
  </section>
</template>
