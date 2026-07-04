<script setup lang="ts">
import type { BacktestSummary } from '@/types/backtests';
import { formatMoney, formatPct } from '@/utils/backtests';

const props = defineProps<{ summary: BacktestSummary }>();
const cards = [
  ['总收益', () => formatPct(props.summary.totalReturnPct)],
  ['年化收益', () => formatPct(props.summary.annualizedReturnPct)],
  ['基准收益', () => formatPct(props.summary.benchmarkReturnPct)],
  ['超额收益', () => formatPct(props.summary.excessReturnPct)],
  ['最大回撤', () => formatPct(props.summary.maxDrawdownPct)],
  ['Sharpe', () => props.summary.sharpeRatio?.toFixed(3) ?? '—'],
  ['最终净值', () => formatMoney(props.summary.finalEquity)],
  ['交易次数', () => String(props.summary.tradeCount ?? '—')],
  ['胜率', () => formatPct(props.summary.winRatePct)],
] as const;
</script>

<template>
  <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
    <div
      v-for="card in cards"
      :key="card[0]"
      class="rounded-2xl border border-border/70 bg-card/94 p-4 shadow-soft-card"
    >
      <p class="text-xs text-muted-text">
        {{ card[0] }}
      </p><p class="mt-2 text-lg font-semibold text-foreground">
        {{ card[1]() }}
      </p>
    </div>
  </div>
</template>
