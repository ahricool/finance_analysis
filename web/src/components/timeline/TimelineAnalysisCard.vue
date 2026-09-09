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
      <span>{{ clockTime(item.eventTime) }}</span>
    </template>
    <p class="break-words text-[15px] font-semibold leading-snug tracking-tight">
      {{ item.title }}
    </p>
    <p
      v-if="item.summary"
      class="mt-1.5 line-clamp-5 break-words text-sm leading-relaxed text-muted-foreground"
    >
      {{ item.summary }}
    </p>
    <p
      v-if="item.relatedSymbols.length"
      class="mt-2 flex flex-wrap items-center gap-1 text-[11px] leading-4"
    >
      <span
        v-for="symbol in item.relatedSymbols.slice(0, 4)"
        :key="symbol"
        class="rounded bg-muted px-1 py-px font-medium tabular-nums text-foreground"
      >{{ symbol }}</span>
    </p>
  </TimelineCardShell>
</template>
