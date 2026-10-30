<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { tradeEngineApi, type TradeSignal } from '@/api/holdings';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';

const props = defineProps<{ symbol: string; market: string; positionId?: number }>();
const signals = ref<TradeSignal[]>([]);
const signalLoading = ref(false);
const signalError = ref<ParsedApiError | null>(null);
const supported = computed(() => props.market === 'CN' || props.market === 'US');
let generation = 0;
let signalRequest = 0;
onBeforeUnmount(() => { generation++; signalRequest++; });
async function loadSignals() {
  const version = generation;
  const request = ++signalRequest;
  const { positionId, market, symbol } = props;
  signals.value = [];
  signalError.value = null;
  if (positionId == null || !supported.value) { signalLoading.value = false; return; }
  signalLoading.value = true;
  try {
    const rows = await tradeEngineApi.signals(market, String(positionId));
    if (version === generation && request === signalRequest) {
      signals.value = rows.filter(row => row.positionId === String(positionId) && row.symbol === symbol);
    }
  } catch (error) {
    if (version === generation && request === signalRequest) signalError.value = getParsedApiError(error);
  } finally {
    if (version === generation && request === signalRequest) signalLoading.value = false;
  }
}
watch(() => [props.symbol, props.market, props.positionId], () => {
  generation++;
  void loadSignals();
}, { immediate: true });
</script>

<template>
  <div
    v-if="positionId != null"
    class="space-y-2"
    data-testid="signal-evidence"
  >
    <h4 class="text-sm font-medium">
      历史调仓建议与当时依据
    </h4>
    <p class="text-xs text-muted-foreground">
      仅展示当时保存的信号依据，不使用最新研究结果解释历史建议。实际操作见下方操作记录，可按时间对照。
    </p>
    <p
      v-if="signalLoading"
      class="text-sm"
    >
      加载中…
    </p>
    <template v-else-if="signalError">
      <ApiErrorAlert :error="signalError" />
      <Button
        size="sm"
        variant="outline"
        @click="loadSignals"
      >
        重试历史建议
      </Button>
    </template>
    <p
      v-else-if="!signals.length"
      class="text-sm text-muted-foreground"
    >
      暂无正式调仓信号；无信号不代表没有执行评估。
    </p>
    <details
      v-for="signal in signals"
      :key="signal.id"
      class="rounded-lg border p-3 text-sm"
    >
      <summary class="cursor-pointer">
        {{ formatDateTimeInDisplayTimezone(signal.evaluatedAt) }} · {{ signal.action }} · 目标 {{ signal.suggestedTargetQuantity ?? '—' }} 股
      </summary>
      <div class="mt-2 space-y-2">
        <p>策略 {{ signal.strategyKey }} · 版本 {{ signal.strategyVersion }}</p>
        <p>{{ signal.reason }}</p>
        <p v-if="signal.llmReason && signal.llmReason !== signal.reason">
          LLM 判断：{{ signal.llmReason }}
        </p>
        <p>当时持仓 {{ signal.evidence.currentQuantity ?? '未记录' }} → 目标 {{ signal.evidence.targetQuantity ?? '未记录' }}</p>
        <p v-if="signal.evidence.portfolioReason">
          组合判断：{{ signal.evidence.portfolioReason }}
        </p>
        <p
          v-for="(item, index) in signal.evidence.strategySignals || []"
          :key="index"
        >
          {{ item.strategyKey }} · {{ item.action }} · {{ item.reason }}
        </p>
        <p v-if="signal.evidence.portfolioRisk">
          当时总仓位 {{ signal.evidence.portfolioRisk.grossExposure ?? '未记录' }} · 上限 {{ signal.evidence.portfolioRisk.maxGrossExposure ?? '未记录' }}
        </p>
        <p v-if="signal.evidence.portfolioRisk?.position">
          当时个股权重 {{ signal.evidence.portfolioRisk.position.weight ?? '未记录' }} · 风险 {{ signal.evidence.portfolioRisk.position.openRisk ?? '未记录' }}
        </p>
      </div>
    </details>
  </div>
</template>
