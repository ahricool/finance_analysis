<script setup lang="ts">
import { computed } from 'vue';
import type { MacroDashboard } from '@/api/macro';
import { Card, CardContent } from '@/components/ui/card';
import BilingualEnum from '@/components/app/BilingualEnum.vue';
import BilingualLabel from '@/components/app/BilingualLabel.vue';
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import MacroSignalDetails from './MacroSignalDetails.vue';
import { formatPercent, formatScore } from '@/utils/quant';
const props = defineProps<{ dashboard: MacroDashboard }>();
const stateCards = computed(() => [
  {
    key: 'rates',
    value: props.dashboard.states.rates,
    names: { EASING: '利率环境宽松', PRESSURE: '利率压力', NEUTRAL: '中性' } as Record<string, string>,
  },
  {
    key: 'credit',
    value: props.dashboard.states.credit,
    names: { HEALTHY: '信用健康', WEAK: '信用走弱', NEUTRAL: '中性' } as Record<string, string>,
  },
  {
    key: 'dollar',
    value: props.dashboard.states.dollar,
    names: { STRONG: '美元偏强', WEAK: '美元偏弱', NEUTRAL: '中性' } as Record<string, string>,
  },
  {
    key: 'volatility',
    value: props.dashboard.states.volatility,
    names: { CALM: '波动平稳', ELEVATED: '波动升高', NEUTRAL: '中性' } as Record<string, string>,
  },
]);
</script>
<template>
  <div
    class="grid grid-cols-2 gap-3 lg:grid-cols-3 min-[87.5rem]:grid-cols-6"
    data-testid="macro-states"
  >
    <Card class="py-0">
      <CardContent class="space-y-3 p-4">
        <div class="text-xs text-muted-foreground">
          <IndicatorHelpLabel
            scope="macro"
            label="macroRegime"
          />
        </div>
        <BilingualEnum
          :value="dashboard.regime"
          size="large"
          :class="dashboard.regime === 'RISK_ON' ? 'text-success' : dashboard.regime === 'RISK_OFF' ? 'text-warning' : dashboard.regime === null ? 'text-muted-foreground' : ''"
        />
        <p class="text-xs text-muted-foreground">
          美股整体风险环境
        </p>
      </CardContent>
    </Card>
    <Card class="py-0">
      <CardContent
        class="space-y-2 p-4"
        data-testid="macro-risk-score"
      >
        <div class="text-xs text-muted-foreground">
          <IndicatorHelpLabel
            scope="macro"
            label="riskScore"
          />
        </div>
        <p class="text-2xl font-semibold tabular-nums">
          {{ dashboard.riskScore === null ? '数据不足' : `${formatScore(dashboard.riskScore, 0)} / 100` }}
        </p>
        <div
          v-if="dashboard.riskScore !== null"
          role="progressbar"
          aria-label="风险得分"
          :aria-valuenow="dashboard.riskScore"
          :aria-valuemin="0"
          :aria-valuemax="100"
          class="h-1 rounded-full bg-muted"
        >
          <div
            class="h-full rounded-full bg-foreground/50"
            :style="{ width: `${dashboard.riskScore}%` }"
          />
        </div>
        <p class="inline-flex flex-wrap items-baseline gap-1 text-xs text-muted-foreground">
          <IndicatorHelpLabel
            scope="macro"
            label="signalCoverage"
            compact
          /> {{ formatPercent(dashboard.signalCoverage, 0) }}
        </p>
        <MacroSignalDetails :dashboard="dashboard" />
      </CardContent>
    </Card>
    <Card
      v-for="card in stateCards"
      :key="card.key"
      class="py-0"
    >
      <CardContent class="space-y-3 p-4">
        <div class="text-xs text-muted-foreground">
          <IndicatorHelpLabel
            scope="macro"
            :label="card.key"
          />
        </div>
        <BilingualLabel
          v-if="card.value != null"
          :zh="card.names[card.value] ?? card.value"
          :en="card.value"
        />
        <p
          v-else
          class="text-lg font-semibold text-muted-foreground"
        >
          数据不足
        </p>
      </CardContent>
    </Card>
  </div>
</template>
