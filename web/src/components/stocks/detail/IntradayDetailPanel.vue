<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { Activity, Check, CircleHelp, Clock3, ShieldAlert, X } from 'lucide-vue-next';
import { formatFixed, formatPercent, isFiniteNumber } from '@/utils/number';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import BilingualLabel from '@/components/app/BilingualLabel.vue';
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import type { StockDetailPanelProps } from './types';
import IntradaySourceEvidence from './IntradaySourceEvidence.vue';
import { intradayConfirmationApi as api, type Confirmation, type Evaluation, type Market } from '@/api/intradayConfirmation';
import { intradayLabel, intradayTrendLabel } from '@/i18n/labels';
import { formatDateTime } from '@/utils/format';

const props = defineProps<StockDetailPanelProps>();
const selected = shallowRef<Confirmation | null>(null);
const loading = ref(false);
const evaluations = shallowRef<Evaluation[]>([]);
const evaluationLoading = ref(false);
const evaluationError = ref(false);
const error = shallowRef<ParsedApiError | null>(null);
const supported = computed(() => props.market === 'CN' || props.market === 'US');
const currentStatus = computed(() => selected.value?.currentStatus ?? 'LEGACY');
const statusTone = computed(() => currentStatus.value === 'ACTIVE'
  ? 'border-emerald-500/25 bg-emerald-500/5 text-emerald-700 dark:text-emerald-300'
  : ['FAILED', 'PENDING_FAILURE', 'WEAKENING'].includes(currentStatus.value)
    ? 'border-amber-500/25 bg-amber-500/5 text-amber-700 dark:text-amber-300'
    : 'border-border bg-muted/25 text-foreground');
const conditions = computed(() => Object.entries(selected.value?.conditions ?? {}).map(([key, value]) => ({
  key, value, label: intradayLabel(key),
  notApplicable: key === 'relativeStrength' && selected.value?.metrics.marketBenchmarkSelf === true,
})));
const timeline = computed(() => [...evaluations.value].reverse());
const priceMetrics = computed(() => {
  const m = selected.value?.metrics ?? {};
  return [
    { label: '开盘至今', value: pct(m.intradayReturn), raw: m.intradayReturn, note: '相对当日开盘' },
    { label: '相对大盘', value: m.marketBenchmarkSelf ? '不适用' : pct(m.relativeToMarket), raw: m.marketBenchmarkSelf ? null : m.relativeToMarket, note: `${m.benchmarkCode ?? '基准暂无'} · 开盘以来` },
    { label: '距全天均价', value: pct(m.sessionMeanDistancePct), raw: m.sessionMeanDistancePct, note: `等权均价 ${num(m.sessionMeanPrice)}` },
    { label: '开盘缺口', value: pct(m.gapPct), raw: m.gapPct, note: typeof m.gapStatus === 'string' ? m.gapStatus : '相对昨日收盘' },
  ];
});
let generation = 0;
let historyGeneration = 0;
let controller: AbortController | undefined;
async function loadHistory() {
  const token = generation, request = ++historyGeneration;
  const row = selected.value, market = props.market;
  if (!row?.currentStatus || row.currentStatus === 'LEGACY' || (market !== 'CN' && market !== 'US')) return;
  evaluationLoading.value = true; evaluationError.value = false;
  try {
    const history = await api.evaluations(row.code, market, props.context?.tradeDate, controller?.signal);
    if (token === generation && request === historyGeneration) evaluations.value = history.items;
  } catch {
    if (token === generation && request === historyGeneration) evaluationError.value = true;
  } finally {
    if (token === generation && request === historyGeneration) evaluationLoading.value = false;
  }
}
async function load() {
  const token = ++generation;
  ++historyGeneration;
  controller?.abort(); controller = new AbortController();
  selected.value = null; error.value = null; loading.value = false;
  evaluations.value = []; evaluationError.value = false; evaluationLoading.value = false;
  const { symbol, market } = props;
  if (market !== 'CN' && market !== 'US') return;
  loading.value = true;
  try {
    const response = await api.detail(symbol, market, props.context?.tradeDate, controller.signal);
    if (token !== generation) return;
    selected.value = response;
    void loadHistory();
  } catch (cause) {
    if (token === generation) { const parsed = getParsedApiError(cause); if (parsed.status !== 404) error.value = parsed; }
  } finally { if (token === generation) loading.value = false; }
}
watch([() => props.symbol, () => props.market, () => props.context?.tradeDate], load, { immediate: true });
onBeforeUnmount(() => { ++generation; ++historyGeneration; controller?.abort(); });
function forwardReturn(value: unknown) { return formatPercent(value, { digits: 2, fallback: '' }); }
function pct(value: unknown) { return formatPercent(value, { digits: 2, signed: true }); }
function num(value: unknown) { return formatFixed(value); }
function stamp(value: unknown) { return typeof value === 'string' ? formatDateTime(value) : '—'; }
function marketTone(value: unknown) { return isFiniteNumber(value) ? value > 0 ? 'text-market-up' : value < 0 ? 'text-market-down' : '' : 'text-muted-foreground'; }
</script>

<template>
  <div
    class="space-y-5"
    data-testid="intraday-detail-panel"
  >
    <div class="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
      <span>{{ context?.tradeDate ? '指定交易日盘中确认' : '当日盘中确认' }}<span
        v-if="context?.tradeDate"
        class="ml-2 font-medium text-foreground"
      >{{ context.tradeDate }}</span></span>
      <span>昨日候选 · 今日价格验证</span>
    </div>
    <div
      v-if="loading"
      class="space-y-4"
      role="status"
      aria-label="正在读取盘中确认"
    >
      <Skeleton class="h-32 w-full rounded-xl" /><Skeleton class="h-64 w-full rounded-xl" />
    </div>
    <AppApiErrorAlert
      v-else-if="error"
      :error="error"
      action-label="重试"
      @action="load"
    />
    <div
      v-else-if="!selected"
      class="flex flex-col items-center gap-3 rounded-xl border border-dashed px-5 py-10 text-center"
    >
      <Activity
        class="size-7 text-muted-foreground"
        aria-hidden="true"
      />
      <p class="text-sm text-muted-foreground">
        {{ supported ? '该股票在所选交易日暂无盘中确认数据，不代表确认失败。' : '此市场暂不支持盘中确认。' }}
      </p>
    </div>
    <template v-else>
      <section
        class="overflow-hidden rounded-xl border"
        :class="statusTone"
        data-testid="intraday-status-overview"
      >
        <div class="flex flex-wrap items-center justify-between gap-5 p-4 sm:p-5">
          <div class="space-y-2">
            <div class="flex items-center gap-2">
              <Activity
                class="size-4"
                aria-hidden="true"
              /><span class="text-xs font-medium">当前观察</span>
            </div>
            <p class="text-2xl font-semibold tracking-tight">
              {{ intradayLabel(currentStatus) }}
            </p>
            <p class="text-xs text-muted-foreground">
              历史：{{ intradayLabel(selected.state) }} · 追高风险：{{ intradayLabel(selected.chaseRisk) }}
            </p>
          </div>
          <div class="flex items-center gap-5 sm:gap-8">
            <div class="text-right">
              <BilingualLabel
                zh="确认分数"
                en="Confirmation score"
                class="text-xs text-muted-foreground"
              />
              <p class="mt-1 text-3xl font-semibold tracking-tight tabular-nums text-foreground">
                {{ formatFixed(selected.confirmationScore, { digits: 1 }) }}<span class="ml-1 text-xs font-normal text-muted-foreground">/100</span>
              </p>
              <p class="mt-1 text-[11px] text-muted-foreground">
                有效权重 {{ selected.availableScoreWeight ?? 0 }}/100
              </p>
            </div>
            <div class="border-l pl-5">
              <ShieldAlert
                class="mb-2 size-4 text-muted-foreground"
                aria-hidden="true"
              /><p class="text-xs text-muted-foreground">
                追高风险
              </p><Badge
                :variant="selected.chaseRisk === 'HIGH' ? 'warning' : 'outline'"
                class="mt-1"
              >
                {{ intradayLabel(selected.chaseRisk) }}
              </Badge>
            </div>
          </div>
        </div>
        <div class="border-t border-current/10 px-4 py-2.5 text-xs text-muted-foreground sm:px-5">
          {{ selected.chaseRisk === 'HIGH' ? '价格扩张明显，确认有效也需单独评估追高风险。' : '分数用于排序；确认结论由价格条件与连续评估决定。' }}
        </div>
      </section>
      <IntradaySourceEvidence
        :confirmation="selected"
        :market="market as Market"
      />
      <section class="space-y-3 rounded-xl border p-4 sm:p-5">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <BilingualLabel
            zh="确认条件"
            en="Confirmation checklist"
            class="text-sm font-semibold"
          /><span class="text-xs text-muted-foreground">价格与相对强弱为核心</span>
        </div>
        <div
          v-if="conditions.length"
          class="grid gap-2 sm:grid-cols-2"
        >
          <div
            v-for="condition in conditions"
            :key="condition.key"
            class="flex min-w-0 items-center gap-2.5 rounded-lg border px-3 py-3"
          >
            <component
              :is="condition.notApplicable || condition.value == null ? CircleHelp : condition.value ? Check : X"
              class="size-4 shrink-0"
              :class="condition.notApplicable || condition.value == null ? 'text-muted-foreground' : condition.value ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'"
              aria-hidden="true"
            />
            <span class="min-w-0 flex-1 text-xs font-medium">{{ condition.label }}</span>
            <span class="text-[11px] text-muted-foreground">{{ condition.notApplicable ? '基准自身，不适用' : condition.value == null ? '数据不足' : condition.value ? '满足' : '未满足' }}</span>
          </div>
        </div>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          历史规则未保存逐项条件，以当时记录的依据为准。
        </p>
        <p class="text-xs leading-relaxed text-muted-foreground">
          空值表示数据不足，不代表负向；趋势与量能仅作辅助。
        </p>
      </section>
      <section class="space-y-3">
        <BilingualLabel
          zh="全天价格结构"
          en="Intraday price structure"
          class="text-sm font-semibold"
        />
        <dl class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div
            v-for="metric in priceMetrics"
            :key="metric.label"
            class="rounded-xl border bg-card p-3 sm:p-4"
          >
            <dt class="text-xs text-muted-foreground">
              {{ metric.label }}
            </dt>
            <dd
              class="mt-2 text-xl font-semibold tracking-tight tabular-nums"
              :class="marketTone(metric.raw)"
            >
              {{ metric.value }}
            </dd>
            <dd class="mt-1 break-words text-[11px] text-muted-foreground">
              {{ metric.note }}
            </dd>
          </div>
        </dl>
        <dl class="grid grid-cols-2 gap-x-5 gap-y-4 rounded-xl border bg-muted/15 p-4 sm:grid-cols-3 sm:p-5">
          <div>
            <dt class="text-xs text-muted-foreground">
              开盘区间
            </dt><dd class="mt-1 text-sm font-medium tabular-nums">
              {{ num(selected.metrics.openingRangeLow) }} – {{ num(selected.metrics.openingRangeHigh) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">
              已闭合分钟线
            </dt><dd class="mt-1 text-sm font-medium tabular-nums">
              {{ selected.metrics.minuteCount ?? '—' }} / {{ selected.metrics.expectedMinuteCount ?? '—' }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">
              量比 · {{ intradayLabel(selected.metrics.volumeStatus) }}
            </dt><dd class="mt-1 text-sm font-medium tabular-nums">
              {{ num(selected.metrics.volumeRatio) }}<span
                v-if="isFiniteNumber(selected.metrics.volumeRatio)"
                class="ml-1 text-xs text-muted-foreground"
              >倍</span>
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">
              近似成交均价
            </dt><dd class="mt-1 text-sm font-medium tabular-nums">
              {{ num(selected.metrics.vwap) }}<span class="ml-2 text-xs text-muted-foreground">{{ pct(selected.metrics.vwapDistancePct) }}</span>
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">
              行情时间
            </dt><dd class="mt-1 text-xs tabular-nums">
              {{ stamp(selected.metrics.quoteTime) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">
              闭合线时间
            </dt><dd class="mt-1 text-xs tabular-nums">
              {{ stamp(selected.metrics.barTime) }}
            </dd>
          </div>
        </dl>
        <details class="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
          <summary class="cursor-pointer font-medium">
            指标口径与数据时间
          </summary>
          <ul class="mt-3 space-y-2 leading-relaxed">
            <li>全天均价为闭合分钟典型价等权平均，无成交量加权；近似成交均价仅作展示。</li><li>量比按日均量 × 已过交易时间比例近似。</li><li>基准报价 {{ stamp(selected.metrics.benchmarkQuoteTime) }} · 确认生成 {{ stamp(selected.generatedAt) }}</li><li>行业：暂无数据 · {{ selected.metrics.industryUnavailableReason ?? '无可靠行业盘中比较' }}</li><li>关联基金：暂无数据 · {{ selected.metrics.etfUnavailableReason ?? '无可靠关联基金比较' }}</li>
          </ul>
        </details>
      </section>
      <section
        class="space-y-3 rounded-xl border p-4 sm:p-5"
        data-testid="intraday-first-confirmation"
      >
        <div class="flex items-center gap-2">
          <Clock3
            class="size-4 text-muted-foreground"
            aria-hidden="true"
          /><BilingualLabel
            zh="首次确认与后续表现"
            en="First confirmation & follow-through"
            class="text-sm font-semibold"
          />
        </div>
        <div class="grid gap-4 sm:grid-cols-[1fr_2fr]">
          <div class="rounded-lg bg-muted/30 p-4">
            <IndicatorHelpLabel
              scope="intraday"
              label="首次确认价格"
              compact
              class="text-xs text-muted-foreground"
            />
            <p class="mt-2 text-2xl font-semibold tabular-nums">
              {{ num(selected.firstConfirmedPrice) }}
            </p>
            <p class="mt-2 text-[11px] leading-relaxed text-muted-foreground">
              报价时间 {{ stamp(selected.firstConfirmedQuoteTime) }}
            </p>
          </div>
          <dl class="grid grid-cols-3 divide-x rounded-lg border py-4">
            <div
              v-for="[label, value] in [['+3D', selected.return3D], ['+5D', selected.return5D], ['+10D', selected.return10D]]"
              :key="String(label)"
              class="min-w-0 px-2 text-center sm:px-4"
            >
              <dt>
                <IndicatorHelpLabel
                  scope="intraday"
                  :label="String(label)"
                  compact
                  class="text-xs text-muted-foreground"
                />
              </dt>
              <dd
                :data-testid="`intraday-detail-return-${label}`"
                class="mt-3 min-h-6 text-base font-semibold tabular-nums sm:text-xl"
                :class="marketTone(value)"
              >
                {{ forwardReturn(value) }}
              </dd>
            </div>
          </dl>
        </div>
        <div class="flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground">
          <span>首次确认 {{ stamp(selected.firstConfirmedAt) }}</span><span>失效时间 {{ stamp(selected.failedAt) }}</span>
        </div>
        <p class="text-xs leading-relaxed text-muted-foreground">
          首次确认时间与价格固定保存，后续状态变化不会重设。确认日不计入，按后续第3/5/10个交易日收盘计算；未到期或缺少价格、复权基准时留空。
        </p>
      </section>
      <section class="space-y-3 rounded-xl border p-4 sm:p-5">
        <BilingualLabel
          zh="趋势辅助"
          en="Trend context"
          class="text-sm font-semibold"
        />
        <dl class="grid gap-3 sm:grid-cols-3">
          <div class="rounded-lg bg-muted/25 p-3">
            <dt class="text-xs text-muted-foreground">
              昨日正式 → 今日临时
            </dt><dd class="mt-2 text-sm font-medium">
              {{ intradayTrendLabel(selected.trend.officialTrendState) }} → {{ intradayTrendLabel(selected.trend.temporaryTrendState) }}
            </dd>
          </div>
          <div class="rounded-lg bg-muted/25 p-3">
            <dt class="text-xs text-muted-foreground">
              生命周期
            </dt><dd class="mt-2 text-sm font-medium">
              {{ intradayLabel(selected.trend.officialLifecycle) }} → {{ intradayLabel(selected.trend.temporaryLifecycle) }}
            </dd>
          </div>
          <div class="rounded-lg bg-muted/25 p-3">
            <dt class="text-xs text-muted-foreground">
              趋势分变化 / 昨日脆弱度
            </dt><dd class="mt-2 text-sm font-medium tabular-nums">
              {{ num(selected.trend.trendScoreDelta) }} / {{ num(selected.trend.officialFragility) }}
            </dd>
          </div>
        </dl>
        <p class="text-xs leading-relaxed text-muted-foreground">
          {{ selected.trend.calculationBasis ?? '缺少趋势基线时，仅使用价格确认。' }}<span v-if="selected.trend.fragilityUnavailableReason"> · {{ selected.trend.fragilityUnavailableReason }}</span>
        </p>
      </section>
      <section class="space-y-3 rounded-xl border p-4 sm:p-5">
        <BilingualLabel
          zh="判断依据"
          en="Decision evidence"
          class="text-sm font-semibold"
        />
        <ul class="grid gap-2 sm:grid-cols-2">
          <li
            v-for="reason in selected.reasons"
            :key="reason.code"
            class="border-l-2 border-muted-foreground/25 py-1 pl-3 text-xs leading-relaxed text-muted-foreground"
          >
            {{ reason.text }}
          </li>
        </ul>
        <p
          v-if="selected.currentPriceRecovered"
          class="rounded-lg bg-amber-500/5 p-3 text-xs leading-relaxed text-amber-700 dark:text-amber-300"
        >
          当前价格行为已恢复，但本次候选当日失效记录不自动撤销。
        </p>
        <details
          v-if="selected.stateReasons.length"
          class="border-t pt-3 text-xs"
        >
          <summary class="cursor-pointer font-medium text-muted-foreground">
            状态变更时依据
          </summary><ul class="mt-3 space-y-2 text-muted-foreground">
            <li
              v-for="reason in selected.stateReasons"
              :key="reason.code"
              class="border-l-2 pl-3 leading-relaxed"
            >
              {{ reason.text }}
            </li>
          </ul>
        </details>
      </section>
      <section class="space-y-3 rounded-xl border p-4 sm:p-5">
        <div class="flex items-center justify-between">
          <BilingualLabel
            zh="评估轨迹"
            en="Evaluation timeline"
            class="text-sm font-semibold"
          /><span class="text-xs text-muted-foreground">{{ evaluations.length }} 次记录 · 最近在前</span>
        </div>
        <Skeleton
          v-if="evaluationLoading"
          class="h-20 w-full"
          aria-label="正在读取评估轨迹"
        />
        <p
          v-else-if="evaluationError"
          class="flex flex-wrap items-center gap-3 text-sm text-muted-foreground"
        >
          评估轨迹暂时无法加载。<Button
            variant="outline"
            size="sm"
            @click="loadHistory"
          >
            重试轨迹
          </Button>
        </p>
        <p
          v-else-if="!evaluations.length"
          class="rounded-lg bg-muted/25 p-4 text-xs text-muted-foreground"
        >
          暂无评估记录；旧规则历史不补造轨迹。
        </p>
        <div
          v-else
          class="max-h-80 space-y-3 overflow-y-auto pr-1"
        >
          <details
            v-for="item in timeline"
            :key="item.evaluatedAt"
            class="rounded-lg border p-3 text-xs"
          >
            <summary class="cursor-pointer">
              <span class="ml-1 inline-flex flex-wrap items-center gap-x-4 gap-y-1 align-middle"><span class="tabular-nums text-muted-foreground">{{ stamp(item.evaluatedAt) }}</span><span class="font-medium">{{ intradayLabel(item.currentStatus) }}</span><span class="tabular-nums">{{ formatFixed(item.confirmationScore, { digits: 1 }) }} 分</span></span>
            </summary>
            <ul class="mt-3 space-y-2 border-t pt-3 text-muted-foreground">
              <li
                v-for="reason in item.reasons"
                :key="reason.code"
                class="leading-relaxed"
              >
                {{ reason.text }}
              </li>
            </ul>
          </details>
        </div>
      </section>
    </template>
  </div>
</template>
