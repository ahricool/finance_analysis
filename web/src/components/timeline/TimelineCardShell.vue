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
      'group relative block w-full min-w-0 overflow-hidden rounded-xl border border-border/80 bg-card p-3 text-left',
      'transition duration-150 hover:-translate-y-px hover:border-foreground/15 hover:shadow-xs',
      'before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:opacity-70',
      accent,
    ]"
    @click="$emit('open')"
  >
    <div class="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px] leading-4 text-muted-foreground">
      <span>{{ kindLabel(item) }}</span>
      <span v-if="item.market">{{ marketLabel(item.market) }}</span>
      <slot name="meta" />
      <span
        class="rounded px-1 py-px font-medium tabular-nums"
        :class="scoreClass"
      >{{ score }}</span>
      <time
        class="tabular-nums"
        :datetime="item.eventTime"
      >{{ shortDate(item.eventTime) }}</time>
    </div>
    <div class="mt-2 min-w-0 overflow-hidden">
      <slot />
    </div>
  </button>
</template>
