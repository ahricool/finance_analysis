<script setup lang="ts">
import { computed } from 'vue';
import type { MacroDashboard } from '@/api/macro';
import { Card, CardContent } from '@/components/ui/card';
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import MacroSignalDetails from './MacroSignalDetails.vue';
import { regimeLabel } from './display';
import { formatPercent, formatScore } from '@/utils/quant';
const props = defineProps<{ dashboard: MacroDashboard }>();
const stateCards = computed(() => [
  { key: 'rates', label: 'Rates', value: props.dashboard.states.rates, names: { EASING: '利率环境宽松', PRESSURE: '利率压力', NEUTRAL: '中性' } as Record<string, string>, help: '使用 TLT 趋势观察长期利率环境。TLT 上行通常对应长端收益率回落，下行对应利率压力上升。' },
  { key: 'credit', label: 'Credit', value: props.dashboard.states.credit, names: { HEALTHY: '信用健康', WEAK: '信用走弱', NEUTRAL: '中性' } as Record<string, string>, help: '通过 HYG / LQD 相对表现观察信用风险偏好。比值走强通常代表高收益信用表现更强。' },
  { key: 'dollar', label: 'Dollar', value: props.dashboard.states.dollar, names: { STRONG: '美元偏强', WEAK: '美元偏弱', NEUTRAL: '中性' } as Record<string, string>, help: '通过 UUP 观察美元趋势。美元快速走强通常代表全球金融条件趋紧。' },
  { key: 'volatility', label: 'Volatility', value: props.dashboard.states.volatility, names: { CALM: '波动平稳', ELEVATED: '波动升高', NEUTRAL: '中性' } as Record<string, string>, help: '通过 VIX 趋势观察市场波动状态。' },
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
            label="Macro Regime"
            description="后端综合权益、信用及跨资产信号判断的宏观风险环境，用于辅助仓位与风险判断。"
          />
        </div>
        <p
          class="text-2xl font-semibold"
          :class="dashboard.regime === 'RISK_ON' ? 'text-success' : dashboard.regime === 'RISK_OFF' ? 'text-warning' : dashboard.regime === null ? 'text-muted-foreground' : ''"
        >
          {{ regimeLabel(dashboard.regime) }}
        </p>
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
            label="Risk Score"
            description="由权益、信用、风险偏好、波动率等多个透明信号组合。仅使用数据完整且新鲜的信号。"
          />
        </div>
        <p class="text-2xl font-semibold tabular-nums">
          {{ dashboard.riskScore === null ? '数据不足' : `${formatScore(dashboard.riskScore, 0)} / 100` }}
        </p>
        <div
          v-if="dashboard.riskScore !== null"
          role="progressbar"
          aria-label="Risk Score"
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
        <p class="text-xs text-muted-foreground">
          Signal Coverage {{ formatPercent(dashboard.signalCoverage, 0) }}
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
            :label="card.label"
            :description="card.help"
          />
        </div>
        <p
          class="text-lg font-semibold"
          :class="card.value === null ? 'text-muted-foreground' : ''"
        >
          {{ card.value === null ? '数据不足' : card.names[card.value] }}
        </p>
        <p class="text-xs text-muted-foreground">
          {{ card.value ?? '—' }}
        </p>
      </CardContent>
    </Card>
  </div>
</template>
