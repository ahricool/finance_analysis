<script setup lang="ts">
import OptionHelp from './OptionHelp.vue';
import type { OptionScores } from '@/api/optionsIntelligence';
import { formatOptionNumber, reasonLabel } from './labels';

defineProps<{ scores: OptionScores | null | undefined }>();

const cards = [
  {
    key: 'bearishDemand' as const,
    name: '看跌保护需求',
    en: 'Bearish Demand',
    totalWeights: 6,
    accent: 'text-red-600 dark:text-red-400',
    bar: 'bg-red-500/80 dark:bg-red-400/80',
    border: 'border-red-500/20',
  },
  {
    key: 'unusualActivity' as const,
    name: '异常交易活动',
    en: 'Unusual Activity',
    totalWeights: 5,
    accent: 'text-amber-600 dark:text-amber-400',
    bar: 'bg-amber-500/80 dark:bg-amber-400/80',
    border: 'border-amber-500/20',
  },
  {
    key: 'liquidityRisk' as const,
    name: '流动性风险',
    en: 'Liquidity Risk',
    totalWeights: 1,
    accent: 'text-orange-600 dark:text-orange-400',
    bar: 'bg-orange-500/80 dark:bg-orange-400/80',
    border: 'border-orange-500/20',
  },
];

function methodText(method: string | undefined, confidence: string | undefined, initialRulesUsed?: boolean) {
  const conf = confidence === 'medium' ? '中等可信度' : '低可信度';
  if (method === 'historical_percentiles') {
    return `历史分位数 · ${conf}${initialRulesUsed ? '（含初始规则）' : ''}`;
  }
  if (method === 'observed_quote_liquidity_rules') {
    return '采集报价研究代理 · 低可信度';
  }
  return `初始规则 · ${conf}`;
}
</script>

<template>
  <div class="grid gap-3.5 sm:grid-cols-3">
    <div
      v-for="card in cards"
      :key="card.key"
      class="flex flex-col justify-between rounded-xl border bg-card/90 p-4 transition-colors"
      :class="(scores?.[card.key]?.value ?? 0) >= 80 ? card.border : ''"
    >
      <div>
        <div class="flex items-start justify-between gap-2">
          <div>
            <p class="text-sm font-medium text-foreground">
              <OptionHelp
                :label="card.name"
                :en="card.en"
                compact
              />
            </p>
            <p class="text-[11px] tracking-wide text-muted-foreground">
              {{ card.en }}
            </p>
          </div>
          <span
            v-if="scores?.[card.key]?.evidenceCount != null"
            class="rounded-md border bg-muted/50 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
          >
            证据 {{ scores[card.key].evidenceCount }}/{{ card.totalWeights }}
          </span>
        </div>

        <div class="my-3 flex items-baseline justify-between gap-2">
          <p
            class="text-3xl font-semibold tracking-tight tabular-nums"
            :class="scores?.[card.key]?.value == null ? 'text-muted-foreground/70' : card.accent"
          >
            {{ formatOptionNumber(scores?.[card.key]?.value, 1) }}
          </p>
          <span
            v-if="(scores?.[card.key]?.value ?? 0) >= 80"
            class="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium"
            :class="card.accent"
          >
            重点关注
          </span>
        </div>
      </div>

      <div>
        <div class="h-1.5 overflow-hidden rounded-full bg-muted/80">
          <div
            v-if="scores?.[card.key]?.value != null"
            class="h-full rounded-full transition-all duration-300"
            :class="card.bar"
            :style="{ width: `${Math.min(100, Math.max(0, scores[card.key].value!))}%` }"
          />
        </div>
        <p class="mt-2.5 text-xs text-muted-foreground">
          {{ methodText(scores?.[card.key]?.method, scores?.[card.key]?.confidence, scores?.[card.key]?.initialRulesUsed) }}
        </p>
        <p
          v-if="scores?.[card.key]?.reason"
          class="mt-1 text-xs text-muted-foreground/90"
        >
          {{ reasonLabel(scores[card.key].reason!) }}
        </p>
      </div>
    </div>
  </div>
</template>
