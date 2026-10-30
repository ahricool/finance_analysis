<script setup lang="ts">
import { formatRank } from '@/utils/rank';
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import type { StockDetailPanelProps } from './types';
import PageHeader from '@/components/layout/PageHeader.vue';
import { quantApi } from '@/api/quant';
import type { QuantSignal } from '@/types/quant';
import { formatPredictedReturn, formatScore } from '@/utils/quant';
const props = defineProps<StockDetailPanelProps>();
const item = shallowRef<QuantSignal | null>(null);
const history = shallowRef<QuantSignal[]>([]);
const loading = ref(false);
const error = shallowRef<ParsedApiError | null>(null);
const supported = computed(() => props.market === 'CN' || props.market === 'US');
let generation = 0;
async function load() {
  const token = ++generation;
  item.value = null; history.value = []; error.value = null; loading.value = false;
  if (props.market !== 'CN' && props.market !== 'US') return;
  const market = props.market, symbol = props.symbol, date = props.context?.tradeDate;
  loading.value = true;
  try {
    const values = await Promise.all([
      date ? quantApi.signal(symbol, market, date) : quantApi.signal(symbol, market),
      date ? quantApi.signalHistory(symbol, market, date) : quantApi.signalHistory(symbol, market),
    ]);
    if (token === generation) [item.value, history.value] = values;
  } catch (cause) { if (token === generation) { const parsed = getParsedApiError(cause); if (parsed.status !== 404) error.value = parsed; } }
  finally { if (token === generation) loading.value = false; }
}
watch([() => props.symbol, () => props.market, () => props.context?.tradeDate], load, { immediate: true });
onBeforeUnmount(() => { ++generation; });
</script>
<template>
  <div
    class="space-y-4"
    data-testid="quant-detail-panel"
  >
    <p class="text-sm text-muted-foreground">
      正式量化信号 · {{ context?.tradeDate || '最新可用日期' }} · 历史记录截至所选日期。
    </p>
    <p
      v-if="loading"
      role="status"
    >
      正在读取量化信号…
    </p>
    <AppApiErrorAlert
      v-else-if="error"
      :error="error"
    />
    <p
      v-else-if="!item"
      class="text-sm text-muted-foreground"
    >
      {{ supported ? '该股票在所选日期暂无正式量化信号。' : '此市场暂不支持量化信号。' }}
    </p>
    <Button
      v-if="error"
      variant="outline"
      @click="load"
    >
      重试
    </Button>
    <template v-if="item">
      <PageHeader
        variant="section"
        :title="'量化信号'"
        en="Signal Detail"
        :description="`${item.tradeDate} · 排名 ${formatRank(item.universeRank, item.rankTotal)} · ${item.signal} · 预测 ${formatPredictedReturn(item.predictedReturn)}`"
      />
      <section class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div
          v-for="row in [
            ['最终得分', item.finalScore],
            ['风险惩罚', item.riskPenalty],
            ['市场', item.marketScore],
            ['横截面', item.crossSectionScore],
            ['时间序列', item.timeSeriesScore],
          ]"
          :key="String(row[0])"
          class="rounded-xl border border-border bg-card p-3"
        >
          <p class="text-xs text-muted-foreground">
            <IndicatorHelpLabel
              scope="quant"
              :label="String(row[0])"
              compact
            />
          </p>
          <p class="mt-1 font-semibold">
            {{ formatScore(row[1] as number | null) }}
          </p>
        </div>
      </section>
      <section class="rounded-xl border bg-card p-4">
        <h3 class="text-sm font-semibold">
          原因说明
        </h3>
        <ul class="mt-2 list-disc space-y-1 pl-5 text-sm">
          <li
            v-for="reason in item.reasons"
            :key="reason"
          >
            {{ reason }}
          </li>
        </ul>
      </section>
      <section class="rounded-xl border bg-card p-4">
        <h3 class="mb-2 text-sm font-semibold">
          历史
        </h3>
        <div class="space-y-2 text-sm">
          <div
            v-for="row in history"
            :key="row.id"
            class="flex justify-between border-b border-border pb-2"
          >
            <span>{{ row.tradeDate }}</span><span>排名 {{ formatRank(row.universeRank, row.rankTotal) }} · 得分 {{ formatScore(row.finalScore) }}</span>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
