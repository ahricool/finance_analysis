<script setup lang="ts">
import { computed } from 'vue';
import type { TimelineItem } from '@/api/timeline';
import { importanceNames, kindLabel, marketLabel, shortDate } from './timelineFormat';

const props = defineProps<{ item: TimelineItem }>();
defineEmits<{ open: [] }>();

const accent = computed(() => ({
  event: 'before:bg-primary/70',
  news: 'before:bg-sky-500/70',
  analysis: 'before:bg-amber-500/70',
}[props.item.category]));

const scoreClass = computed(() =>
  props.item.importance === 'critical'
    ? 'bg-destructive/10 text-destructive'
    : props.item.importance === 'high'
      ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400'
      : 'bg-muted text-muted-foreground',
);
const score = computed(() =>
  typeof props.item.importanceScore === 'number' && props.item.importanceScore > 0
    ? `${props.item.importanceScore}/10`
    : importanceNames[props.item.importance],
);
</script>

<template>
  <button
    type="button"
    data-testid="timeline-item"
    :aria-label="`查看${item.title}`"
    :class="[
      'group relative w-full overflow-hidden rounded-xl border border-border bg-card p-4 text-left shadow-sm',
      'transition duration-200 hover:-translate-y-0.5 hover:border-foreground/20 hover:shadow-md sm:p-5',
      'before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:opacity-70',
      accent,
    ]"
    @click="$emit('open')"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span class="font-semibold text-foreground">{{ kindLabel(item) }}</span>
        <span v-if="item.market">· {{ marketLabel(item.market) }}</span>
        <slot name="meta" />
      </div>
      <div class="flex shrink-0 items-center gap-2 text-xs">
        <span
          class="rounded-md px-1.5 py-0.5 font-medium tabular-nums"
          :class="scoreClass"
        >{{ score }}</span>
        <time
          class="tabular-nums text-muted-foreground"
          :datetime="item.eventTime"
        >{{ shortDate(item.eventTime) }}</time>
      </div>
    </div>
    <div class="mt-3 min-w-0">
      <slot />
    </div>
  </button>
</template>
