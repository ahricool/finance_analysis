<script setup lang="ts">
import type { TimelineItem } from '@/api/timeline';
import TimelineCardShell from './TimelineCardShell.vue';
import { clockTime } from './timelineFormat';

defineProps<{ item: TimelineItem }>();
defineEmits<{ open: [] }>();
</script>

<template>
  <TimelineCardShell
    :item="item"
    @open="$emit('open')"
  >
    <template #meta>
      <span>· {{ clockTime(item.eventTime) }}</span>
    </template>
    <p class="break-words text-base font-semibold leading-snug">
      {{ item.title }}
    </p>
    <p
      v-if="item.summary"
      class="mt-1 line-clamp-2 text-sm leading-relaxed text-muted-foreground"
    >
      {{ item.summary }}
    </p>
    <p class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <span
        v-if="item.impact"
        class="font-medium"
        :class="item.impact === 'bullish' ? 'text-market-up' : item.impact === 'bearish' ? 'text-market-down' : 'text-muted-foreground'"
      >{{ item.impact }} {{ item.impactScore !== null && item.impactScore > 0 ? '+' : '' }}{{ item.impactScore }}</span>
      <span
        v-for="symbol in item.relatedSymbols.slice(0, 6)"
        :key="symbol"
        class="rounded bg-muted px-1.5 py-0.5 font-medium tabular-nums text-foreground"
      >{{ symbol }}</span>
    </p>
  </TimelineCardShell>
</template>
