<script setup lang="ts">
import { quantApi } from '@/api/quant';import { getParsedApiError,type ParsedApiError } from '@/api/error';import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';import type { QuantSignal } from '@/types/quant';import {formatPercent,formatPredictedReturn,formatScore} from '@/utils/quant';import {ref,watch} from 'vue';import {useRoute} from 'vue-router';import {useQuantMarket} from '@/composables/useQuantMarket';const route=useRoute();const {market}=useQuantMarket();const item=ref<QuantSignal|null>(null);const history=ref<QuantSignal[]>([]);const error=ref<ParsedApiError|null>(null);let requestVersion=0;watch([market,()=>route.params.code],async([current,code])=>{const version=++requestVersion;item.value=null;history.value=[];error.value=null;try{const values=await Promise.all([quantApi.signal(String(code),current),quantApi.signalHistory(String(code),current)]);if(version===requestVersion)[item.value,history.value]=values;}catch(e){if(version===requestVersion)error.value=getParsedApiError(e);}},{immediate:true});
</script>
<template>
  <div class="space-y-4">
    <RouterLink
      to="/market/quant/signals"
      class="text-sm text-primary"
    >
      ← 返回排名
    </RouterLink><ApiErrorAlert
      v-if="error"
      :error="error"
    /><template v-if="item">
      <header>
        <h2 class="text-lg font-semibold">
          {{ item.code }}
        </h2><p class="text-xs text-muted-text">
          排名 {{ item.universeRank??'—' }} · {{ item.signal }} · 预测 {{ formatPredictedReturn(item.predictedReturn) }} · 目标 {{ formatPercent(item.targetPosition) }}
        </p>
      </header><section class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div
          v-for="row in [['最终得分',item.finalScore],['原始得分',item.rawFinalScore],['门控得分',item.gatedFinalScore],['风险惩罚',item.riskPenalty],['市场',item.marketScore],['行业',item.sectorScore],['横截面',item.crossSectionScore],['时间序列',item.timeSeriesScore]]"
          :key="String(row[0])"
          class="rounded-xl border border-border bg-card p-3"
        >
          <p class="text-xs text-muted-text">
            {{ row[0] }}
          </p><p class="mt-1 font-semibold">
            {{ formatScore(row[1] as number|null) }}
          </p>
        </div>
      </section><section class="rounded-2xl border border-border bg-card p-4">
        <h3 class="text-sm font-semibold">
          原因说明
        </h3><ul class="mt-2 list-disc space-y-1 pl-5 text-sm">
          <li
            v-for="reason in item.reasons"
            :key="reason"
          >
            {{ reason }}
          </li>
        </ul><details class="mt-4 text-xs">
          <summary class="cursor-pointer text-muted-text">
            查看原始数据
          </summary><pre class="mt-2 overflow-auto rounded bg-background p-3">{{ JSON.stringify(item.scoreComponents,null,2) }}</pre>
        </details>
      </section><section class="rounded-2xl border border-border bg-card p-4">
        <h3 class="mb-2 text-sm font-semibold">
          历史
        </h3><div class="space-y-2 text-sm">
          <div
            v-for="row in history"
            :key="row.id"
            class="flex justify-between border-b border-border pb-2"
          >
            <span>{{ row.tradeDate }}</span><span>排名 {{ row.universeRank??'—' }} · 得分 {{ formatScore(row.finalScore) }}</span>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
