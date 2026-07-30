<script setup lang="ts">
import type { BacktestSummary } from '@/types/backtests';
import { formatMoney, formatPct } from '@/utils/backtests';

const props = defineProps<{ summary: BacktestSummary }>();
const metrics = [
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
  <dl
    class="grid grid-cols-2 gap-x-6 gap-y-4 rounded-xl border bg-card p-4 sm:grid-cols-3 xl:grid-cols-5"
  >
    <div
      v-for="metric in metrics"
      :key="metric[0]"
    >
      <dt class="text-xs text-muted-foreground">
        {{ metric[0] }}
      </dt>
      <dd class="mt-1 font-mono text-lg font-semibold tabular-nums tracking-tight">
        {{ metric[1]() }}
      </dd>
    </div>
  </dl>
</template>
