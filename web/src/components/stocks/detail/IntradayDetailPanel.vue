<script setup lang="ts">
import { formatFixed, formatPercent } from '@/utils/number';
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import { Button } from '@/components/ui/button';
import type { StockDetailPanelProps } from './types';
import { intradayConfirmationApi as api, type Confirmation, type Evaluation } from '@/api/intradayConfirmation';
import { intradayLabel, intradayTrendLabel } from '@/i18n/labels';
import { formatDateTime } from '@/utils/format';
const props = defineProps<StockDetailPanelProps>();
const selected = shallowRef<Confirmation | null>(null);
const loading = ref(false);
const evaluations = shallowRef<Evaluation[]>([]);
const evaluationError = ref(false);
const error = shallowRef<ParsedApiError | null>(null);
const supported = computed(() => props.market === 'CN' || props.market === 'US');
let generation = 0;
let controller: AbortController | undefined;
async function load() {
  const token = ++generation;
  controller?.abort(); controller = new AbortController();
  selected.value = null; error.value = null; loading.value = false; evaluations.value = []; evaluationError.value = false;
  if (props.market !== 'CN' && props.market !== 'US') return;
  loading.value = true;
  try { const response = await api.detail(props.symbol, props.market, props.context?.tradeDate, controller.signal); if (token === generation) {
    selected.value = response;
    if (response.currentStatus && response.currentStatus !== 'LEGACY') {
      try { const history = await api.evaluations(props.symbol, props.market, props.context?.tradeDate, controller.signal); if (token === generation) evaluations.value = history.items; }
      catch { if (token === generation) evaluationError.value = true; }
    }
  } }
  catch (cause) { if (token === generation) { const parsed = getParsedApiError(cause); if (parsed.status !== 404) error.value = parsed; } }
  finally { if (token === generation) loading.value = false; }
}
watch([() => props.symbol, () => props.market, () => props.context?.tradeDate], load, { immediate: true });
onBeforeUnmount(() => { ++generation; controller?.abort(); });
function forwardReturn(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : ''; }
function pct(value: unknown) { return formatPercent(value, { digits: 2, fallback: '—' }); }
function num(value: unknown) { return formatFixed(value, { fallback: '—' }); }
function stamp(value: unknown) { return typeof value === 'string' ? formatDateTime(value) : '—'; }
</script>
<template>
  <div
    class="space-y-4"
    data-testid="intraday-detail-panel"
  >
    <p class="text-sm text-muted-foreground">
      {{ context?.tradeDate ? '指定交易日盘中确认' : '当日盘中确认' }} · 冻结候选逻辑 → 盘中价格行为 → 确认结论。
    </p>
    <p
      v-if="context?.tradeDate"
      class="text-xs text-muted-foreground"
    >
      确认交易日 {{ context.tradeDate }}；展示该日保存的快照，行情时间与确认生成时间分别列示。
    </p>
    <p
      v-if="loading"
      role="status"
    >
      正在读取盘中确认…
    </p>
    <AppApiErrorAlert
      v-else-if="error"
      :error="error"
    />
    <p
      v-else-if="!selected"
      class="text-sm text-muted-foreground"
    >
      {{ supported ? '该股票在所选交易日暂无盘中确认数据，不代表确认失败。' : '此市场暂不支持盘中确认。' }}
    </p>
    <Button
      v-if="error"
      variant="outline"
      @click="load"
    >
      重试
    </Button>
    <template v-if="selected">
      <p class="text-sm">
        确认分数 {{ selected.confirmationScore == null ? '—' : selected.confirmationScore.toFixed(1) }} · 有效权重 {{ selected.availableScoreWeight ?? 0 }}/100 · 候选来源 {{ (selected.candidateSources?.length ? selected.candidateSources : [selected.candidateSource]).map(intradayLabel).join(' / ') }}
      </p>
      <p class="text-xs text-muted-foreground">
        首次确认 {{ stamp(selected.firstConfirmedAt) }} · 失效时间 {{ stamp(selected.failedAt) }}。空值表示数据不足，不代表负向。
      </p>
      <section
        class="space-y-2"
        data-testid="intraday-first-confirmation"
      >
        <h3 class="font-semibold">
          <IndicatorHelpLabel
            scope="intraday"
            label="首次确认价格"
          />
        </h3>
        <p>首次确认价格 {{ num(selected.firstConfirmedPrice) }} · 报价时间 {{ stamp(selected.firstConfirmedQuoteTime) }}</p>
        <p class="text-xs text-muted-foreground">
          首次确认时间与价格固定保存，后续状态变化不会重设。收益按同口径前复权价格计算。
        </p>
        <dl class="grid grid-cols-3 gap-3">
          <div
            v-for="[label, value] in [['+3D', selected.return3D], ['+5D', selected.return5D], ['+10D', selected.return10D]]"
            :key="String(label)"
          >
            <dt>
              <IndicatorHelpLabel
                scope="intraday"
                :label="String(label)"
                compact
              />
            </dt>
            <dd
              :data-testid="`intraday-detail-return-${label}`"
              class="min-h-5 tabular-nums"
            >
              {{ forwardReturn(value) }}
            </dd>
          </div>
        </dl>
        <p class="text-xs text-muted-foreground">
          确认日不计入，按后续第3/5/10个交易日收盘计算；未到期或缺少价格、复权基准时留空。
        </p>
      </section>
      <section class="space-y-2">
        <h3 class="font-semibold">
          昨日逻辑 · {{ selected.candidateTradeDate }}
        </h3><p>{{ selected.candidateReason.join('；') }}</p><p class="text-sm text-muted-foreground">
          正式结果生成于 {{ stamp(selected.sourceGeneratedAt) }}
        </p>
      </section>
      <section class="space-y-2">
        <h3 class="font-semibold">
          全天价格结构
        </h3>
        <p>行情时间 {{ stamp(selected.metrics.quoteTime) }} · 闭合线时间 {{ stamp(selected.metrics.barTime) }} · 确认生成 {{ stamp(selected.generatedAt) }}</p>
        <p>开盘缺口 {{ pct(selected.metrics.gapPct) }} · {{ selected.metrics.gapStatus }}</p>
        <p>开盘至今 {{ pct(selected.metrics.intradayReturn) }} · 全天等权均价 {{ num(selected.metrics.sessionMeanPrice) }} · 距均价 {{ pct(selected.metrics.sessionMeanDistancePct) }}</p>
        <p>已闭合分钟线 {{ selected.metrics.minuteCount ?? '—' }} / {{ selected.metrics.expectedMinuteCount ?? '—' }} · 无成交量加权</p>
        <p>开盘区间 {{ num(selected.metrics.openingRangeLow) }} – {{ num(selected.metrics.openingRangeHigh) }}</p>
        <p>近似成交均价 {{ num(selected.metrics.vwap) }} · 距离 {{ pct(selected.metrics.vwapDistancePct) }}</p>
        <p>量比 {{ num(selected.metrics.volumeRatio) }}x · {{ intradayLabel(selected.metrics.volumeStatus) }}（日均量 × 交易时间比例近似）</p>
      </section>
      <section class="space-y-2">
        <h3 class="font-semibold">
          相对强弱（统一以开盘为基准）
        </h3><p>{{ selected.metrics.benchmarkCode }}：{{ pct(selected.metrics.relativeToMarket) }} · 数据时间 {{ stamp(selected.metrics.benchmarkQuoteTime) }}</p><p>行业：暂无数据 · {{ selected.metrics.industryUnavailableReason }}</p><p>关联基金：暂无数据 · {{ selected.metrics.etfUnavailableReason }}</p>
      </section>
      <section class="space-y-2">
        <h3 class="font-semibold">
          趋势辅助 · 昨日正式 → 今日临时
        </h3>
        <p>{{ intradayTrendLabel(selected.trend.officialTrendState) }} → {{ intradayTrendLabel(selected.trend.temporaryTrendState) }}</p>
        <p>生命周期 {{ intradayLabel(selected.trend.officialLifecycle) }} → {{ intradayLabel(selected.trend.temporaryLifecycle) }}</p>
        <p>趋势分变化 {{ num(selected.trend.trendScoreDelta) }} · 脆弱度 {{ num(selected.trend.official脆弱度) }} → 暂无数据</p>
        <p class="text-sm text-muted-foreground">
          {{ selected.trend.calculationBasis }}。{{ selected.trend.fragilityUnavailableReason }}
        </p>
      </section>
      <section class="space-y-2">
        <h3 class="font-semibold">
          {{ intradayLabel(selected.currentStatus ?? 'LEGACY') }} · 历史：{{ intradayLabel(selected.state) }} · 追高风险：{{ intradayLabel(selected.chaseRisk) }}
        </h3><ul class="list-disc pl-5">
          <li
            v-for="reason in selected.reasons"
            :key="reason.code"
          >
            {{ reason.text }}
          </li>
        </ul>
        <p v-if="selected.currentPriceRecovered">
          当前价格行为已恢复，但本次候选当日失效记录不自动撤销。
        </p>
        <template v-if="selected.stateReasons.length">
          <p>状态变更时依据：</p><ul class="list-disc pl-5">
            <li
              v-for="reason in selected.stateReasons"
              :key="reason.code"
            >
              {{ reason.text }}
            </li>
          </ul>
        </template>
      </section>
      <section class="space-y-3 rounded-lg border p-4">
        <h3 class="font-semibold">
          确认条件
        </h3>
        <div class="grid gap-2 sm:grid-cols-2">
          <p
            v-for="(value, key) in selected.conditions"
            :key="key"
            class="rounded bg-muted/40 px-3 py-2 text-sm"
          >
            {{ intradayLabel(key) }}<span class="float-right text-muted-foreground">{{ key === 'relativeStrength' && selected.metrics.marketBenchmarkSelf ? '基准自身，不适用' : value === null ? '数据不足' : value ? '满足' : '未满足' }}</span>
          </p>
        </div>
      </section>
      <section class="space-y-3">
        <h3 class="font-semibold">
          评估轨迹
        </h3>
        <p
          v-if="evaluationError"
          class="text-sm text-muted-foreground"
        >
          评估轨迹暂时无法加载。<Button
            variant="outline"
            @click="load"
          >
            重试
          </Button>
        </p>
        <p
          v-else-if="!evaluations.length"
          class="text-sm text-muted-foreground"
        >
          暂无评估记录；旧规则历史不补造轨迹。
        </p>
        <div
          v-else
          class="max-h-72 space-y-2 overflow-y-auto"
        >
          <div
            v-for="item in [...evaluations].reverse()"
            :key="item.evaluatedAt"
            class="rounded-lg border p-3 text-sm"
          >
            <div class="flex flex-wrap justify-between gap-2">
              <span>{{ stamp(item.evaluatedAt) }}</span><span>{{ intradayLabel(item.currentStatus) }} · {{ item.confirmationScore == null ? '—' : item.confirmationScore.toFixed(1) }} 分</span>
            </div>
            <p class="mt-1 text-xs text-muted-foreground">
              {{ item.reasons.map(r => r.text).join('；') }}
            </p>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
