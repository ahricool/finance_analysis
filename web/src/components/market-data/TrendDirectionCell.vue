<script setup lang="ts">
import type { TrendDirection } from '@/api/intradayOptions';
import { directions, tone } from '@/components/intraday-options/labels';
import { TableCell } from '@/components/ui/table';

defineProps<{ direction?: TrendDirection | null }>();
</script>

<template>
  <TableCell
    class="whitespace-nowrap"
    :class="tone(direction === 'bullish' ? 1 : direction === 'bearish' ? -1 : 0)"
  >
    {{ direction ? directions[direction] : '—' }}
  </TableCell>
</template>
