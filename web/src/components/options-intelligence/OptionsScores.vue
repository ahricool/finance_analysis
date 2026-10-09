<script setup lang="ts">
import OptionHelp from './OptionHelp.vue';
import type { OptionScores } from '@/api/optionsIntelligence';
import { formatOptionNumber, reasonLabel } from './labels';
defineProps<{ scores: OptionScores | null | undefined }>();
const cards = [
  { key: 'bearishDemand' as const, name: '看跌保护需求', en: 'Bearish Demand', color: 'text-red-600 dark:text-red-400' },
  { key: 'unusualActivity' as const, name: '异常交易活动', en: 'Unusual Activity', color: 'text-amber-600 dark:text-amber-400' },
  { key: 'liquidityRisk' as const, name: '流动性风险', en: 'Liquidity Risk', color: 'text-orange-600 dark:text-orange-400' },
];
</script>
<template>
  <div class="grid gap-3 sm:grid-cols-3">
    <div
      v-for="card in cards"
      :key="card.key"
      class="rounded-xl border bg-card p-4"
    >
      <p class="text-sm">
        <OptionHelp
          :label="card.name"
          :en="card.en"
          compact
        />
      </p>
      <p class="text-xs text-muted-foreground">
        {{ card.en }}
      </p>
      <p
        class="my-2 text-3xl font-semibold tabular-nums"
        :class="card.color"
      >
        {{ formatOptionNumber(scores?.[card.key]?.value, 1) }}
      </p>
      <div class="h-1 rounded bg-muted">
        <div
          class="h-1 rounded bg-current"
          :class="card.color"
          :style="{ width: `${scores?.[card.key]?.value ?? 0}%` }"
        />
      </div>
      <p class="mt-2 text-xs text-muted-foreground">
        {{ scores?.[card.key]?.method === 'historical_percentiles' ? `历史分位数 / ${scores?.[card.key]?.confidence === 'medium' ? '中等可信度' : '低可信度'}` : scores?.[card.key]?.method === 'observed_quote_liquidity_rules' ? '采集报价研究代理 / 低可信度' : '初始规则 / 低可信度' }}
        {{ scores?.[card.key]?.initialRulesUsed && scores?.[card.key]?.method === 'historical_percentiles' ? '（含初始规则）' : '' }}
      </p>
      <p
        v-if="scores?.[card.key]?.reason"
        class="mt-1 text-xs text-muted-foreground"
      >
        {{ reasonLabel(scores[card.key].reason!) }}
      </p>
    </div>
  </div>
</template>
