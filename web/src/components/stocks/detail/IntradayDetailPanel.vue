<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import type { StockDetailPanelProps } from './types';
import { intradayConfirmationApi as api, type Confirmation } from '@/api/intradayConfirmation';
import { formatDateTime } from '@/utils/format';
const props = defineProps<StockDetailPanelProps>();
const selected = shallowRef<Confirmation | null>(null);
const loading = ref(false);
const error = shallowRef<ParsedApiError | null>(null);
const supported = computed(() => props.market === 'CN' || props.market === 'US');
let generation = 0;
async function load() {
  const token = ++generation;
  selected.value = null; error.value = null; loading.value = false;
  if (props.market !== 'CN' && props.market !== 'US') return;
  loading.value = true;
  try { const response = await api.detail(props.symbol, props.market); if (token === generation) selected.value = response; }
  catch (cause) { if (token === generation) { const parsed = getParsedApiError(cause); if (parsed.status !== 404) error.value = parsed; } }
  finally { if (token === generation) loading.value = false; }
}
watch([() => props.symbol, () => props.market], load, { immediate: true });
onBeforeUnmount(() => { ++generation; });
function pct(value: unknown) { return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : 'unavailable'; }
function num(value: unknown) { return typeof value === 'number' ? value.toFixed(2) : 'unavailable'; }
function stamp(value: unknown) { return typeof value === 'string' ? formatDateTime(value) : 'unavailable'; }
</script>
<template>
  <div
    class="space-y-4"
    data-testid="intraday-detail-panel"
  >
    <p class="text-sm text-muted-foreground">
      最新盘中确认 · 昨日逻辑 → 今日价格行为 → 确认结论。仅提供最新已计算快照，不支持历史回放。
    </p>
    <p
      v-if="context?.tradeDate"
      class="text-xs text-muted-foreground"
    >
      来源观察日期 {{ context.tradeDate }}；下方盘中数据以实际行情和确认生成时间为准。
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
      {{ supported ? '该股票暂无最新盘中确认数据，不代表确认失败。' : '此市场暂不支持盘中确认。' }}
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
        确认分数 {{ selected.confirmationScore == null ? 'unavailable' : selected.confirmationScore.toFixed(1) }} · 有效权重 {{ selected.availableScoreWeight ?? 0 }}/100 · 候选来源 {{ selected.candidateSource }}
      </p>
      <p class="text-xs text-muted-foreground">
        首次确认 {{ stamp(selected.firstConfirmedAt) }} · 失效时间 {{ stamp(selected.failedAt) }}。unavailable 表示数据不足，不代表负向。
      </p>
      <section class="space-y-2">
        <h3 class="font-semibold">
          昨日逻辑 · {{ selected.candidateTradeDate }}
        </h3><p>{{ selected.candidateReason.join('；') }}</p><p class="text-sm text-muted-foreground">
          正式结果生成于 {{ stamp(selected.sourceGeneratedAt) }}
        </p>
      </section>
      <section class="space-y-2">
        <h3 class="font-semibold">
          今日 Price Action
        </h3>
        <p>行情时间 {{ stamp(selected.metrics.quoteTime) }} · 闭合线时间 {{ stamp(selected.metrics.barTime) }} · 确认生成 {{ stamp(selected.generatedAt) }}</p>
        <p>Gap {{ pct(selected.metrics.gapPct) }} · {{ selected.metrics.gapStatus }}</p>
        <p>5m {{ pct(selected.metrics.return5M) }} / 15m {{ pct(selected.metrics.return15M) }} / 30m {{ pct(selected.metrics.return30M) }}</p>
        <p>Opening Range {{ num(selected.metrics.openingRangeLow) }} – {{ num(selected.metrics.openingRangeHigh) }}</p>
        <p>provisional VWAP {{ num(selected.metrics.vwap) }} · 距离 {{ pct(selected.metrics.vwapDistancePct) }}</p>
        <p>Volume {{ num(selected.metrics.volumeRatio) }}x · {{ selected.metrics.volumeStatus }}（日均量 × 交易时间比例近似）</p>
      </section>
      <section class="space-y-2">
        <h3 class="font-semibold">
          Relative Strength（统一以开盘为基准）
        </h3><p>{{ selected.metrics.benchmarkCode }}：{{ pct(selected.metrics.relativeToMarket) }} · 数据时间 {{ stamp(selected.metrics.benchmarkQuoteTime) }}</p><p>Industry：unavailable · {{ selected.metrics.industryUnavailableReason }}</p><p>ETF：unavailable · {{ selected.metrics.etfUnavailableReason }}</p>
      </section>
      <section class="space-y-2">
        <h3 class="font-semibold">
          Trend Impact · Official → Temporary
        </h3>
        <p>{{ selected.trend.officialTrendState ?? 'unavailable' }} → {{ selected.trend.temporaryTrendState ?? 'unavailable' }}</p>
        <p>Lifecycle {{ selected.trend.officialLifecycle ?? 'unavailable' }} → {{ selected.trend.temporaryLifecycle ?? 'unavailable' }}</p>
        <p>Trend Score Δ {{ num(selected.trend.trendScoreDelta) }} · Fragility {{ num(selected.trend.officialFragility) }} → unavailable</p>
        <p class="text-sm text-muted-foreground">
          {{ selected.trend.calculationBasis }}。{{ selected.trend.fragilityUnavailableReason }}
        </p>
      </section>
      <section class="space-y-2">
        <h3 class="font-semibold">
          Decision · {{ selected.state }} · Chase Risk {{ selected.chaseRisk }}
        </h3><ul class="list-disc pl-5">
          <li
            v-for="reason in selected.reasons"
            :key="reason.code"
          >
            {{ reason.text }}
          </li>
        </ul>
        <p v-if="selected.currentPriceRecovered">
          当前价格行为已恢复，但本次候选当日 FAILED 不自动恢复。
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
    </template>
  </div>
</template>
