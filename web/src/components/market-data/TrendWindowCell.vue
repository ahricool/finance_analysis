<script setup lang="ts">
import type { WindowScore } from '@/api/intradayOptions';
import { fmt, pct, tone } from '@/components/intraday-options/labels';
import { TableCell } from '@/components/ui/table';

defineProps<{ window?: Pick<WindowScore, 'score' | 'direction' | 'returnPct' | 'dataStatus' | 'availableBars' | 'missingBars'> }>();
function arrow(value: number | null | undefined) { return value === 1 ? '↑' : value === -1 ? '↓' : '→'; }
</script>

<template>
  <TableCell
    class="whitespace-nowrap tabular-nums"
  >
    <template v-if="window?.score != null">
      <span :class="tone(window?.direction)">{{ arrow(window?.direction) }} {{ fmt(window?.score, 0) }}分</span>
      <p class="text-xs text-muted-foreground">
        {{ pct(window?.returnPct) }}
      </p>
      <p
        v-if="window?.dataStatus !== 'ready'"
        class="text-xs text-amber-600 dark:text-amber-400"
      >
        {{ window?.dataStatus === 'warming' ? '开盘不足' : '分钟缺失' }} · 缺{{ window?.missingBars ?? '部分' }}根 · 参考分
      </p>
    </template>
    <template v-else>
      —<p class="text-xs text-muted-foreground">
        {{ window ? `有效${window?.availableBars ?? 0}根 · 数据过少` : '等待有效数据' }}
      </p>
    </template>
  </TableCell>
</template>
