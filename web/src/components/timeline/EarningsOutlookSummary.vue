<script setup lang="ts">
import { computed } from 'vue';
import type { EarningsOutlook } from '@/api/timeline';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import { outlookStatus, guidanceLabels, price, pct } from './earningsFormat';
const props = defineProps<{ outlook: EarningsOutlook }>();
const current = computed(() => props.outlook.status === 'current');
const earningsHigh = computed(() => current.value && props.outlook.earningsHigh &&
  props.outlook.eps?.judgment !== 'unknown' && props.outlook.revenue?.judgment !== 'unknown');
const reactionHigh = computed(() => current.value && props.outlook.reactionHigh && !props.outlook.provisional &&
  props.outlook.responseDirection !== 'uncertain');
</script>
<template>
  <div
    class="mt-3 space-y-2 border-t border-border pt-3 text-xs"
    data-testid="earnings-outlook"
  >
    <div
      v-if="outlook.eps"
      class="space-y-1 rounded-md p-2"
      :class="earningsHigh ? 'border border-primary/30 bg-primary/5' : 'bg-muted/40'"
    >
      <div class="flex flex-wrap gap-2 font-medium">
        <span>EPS {{ outlook.eps.judgment }}</span>
        <span>营收 {{ outlook.revenue?.judgment || 'unknown' }}</span>
        <span>指引 {{ guidanceLabels[outlook.guidance || 'unknown'] }}</span>
      </div>
      <p class="leading-relaxed">
        {{ outlook.conclusion }}
      </p>
      <p>{{ earningsHigh ? '财报判断高置信度' : '财报判断置信度' }} {{ outlook.earningsConfidence }}/10</p>
    </div>
    <div
      v-if="outlook.targetTradingDate"
      class="space-y-1 rounded-md p-2"
      :class="reactionHigh ? 'border border-primary/30 bg-primary/5' : 'bg-muted/40'"
    >
      <p>{{ outlook.targetTradingDate }} · 首个正常交易日{{ outlook.provisional ? '（暂定）' : '' }}</p>
      <p class="font-medium tabular-nums">
        预计收盘 {{ price(outlook.expectedClose) }}
        <span :class="outlook.responseDirection === 'up' ? 'text-market-up' : outlook.responseDirection === 'down' ? 'text-market-down' : ''">
          {{ pct(outlook.expectedReturnPct) }}
        </span>
      </p>
      <p>盘中 {{ price(outlook.intradayLow) }} – {{ price(outlook.intradayHigh) }}</p>
      <p>{{ reactionHigh ? '首日走势高置信度' : '首日走势置信度' }} {{ outlook.reactionConfidence }}/10</p>
    </div>
    <p
      v-if="outlook.eps"
      class="text-[11px] text-muted-foreground"
    >
      模型证据评分，非胜率
    </p>
    <p class="text-muted-foreground">
      {{ outlookStatus[outlook.status] || '信息不足' }}
    </p>
    <p
      v-if="outlook.referencePriceAt"
      class="text-[11px] text-muted-foreground"
    >
      参考 {{ price(outlook.referencePrice) }} · {{ formatDateTimeInDisplayTimezone(outlook.referencePriceAt) }}
    </p>
    <p
      v-if="outlook.generatedAt"
      class="text-[11px] text-muted-foreground"
    >
      更新 {{ formatDateTimeInDisplayTimezone(outlook.generatedAt) }}
    </p>
  </div>
</template>
