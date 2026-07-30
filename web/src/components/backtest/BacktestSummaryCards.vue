<script setup lang="ts">
import type { BacktestSummary } from '@/types/backtests';
import { formatMoney, formatPct } from '@/utils/backtests';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

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
    <Card
      v-for="card in cards"
      :key="card[0]"
    >
      <CardHeader class="pb-1">
        <CardTitle class="text-sm font-medium text-muted-foreground">
          {{ card[0] }}
        </CardTitle>
      </CardHeader>
      <CardContent class="text-2xl font-semibold tracking-tight">
        {{ card[1]() }}
      </CardContent>
    </Card>
  </div>
</template>
