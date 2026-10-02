<script setup lang="ts">
import { computed } from 'vue';
import { enumLabel } from '@/i18n/labels';
import { cn } from '@/utils/cn';

const props = withDefaults(defineProps<{
  value?: string | null;
  /** large stacked | badge/chip compact | inline both */
  size?: 'large' | 'badge' | 'inline';
  /** Force Chinese-only; English in title. Badge size is compact by default. */
  compact?: boolean;
  class?: string;
}>(), {
  size: 'inline',
  compact: undefined,
});

const pair = computed(() => enumLabel(props.value));
/** Badge/pill/chip containers are fixed-height — never stack English inside them. */
const isCompact = computed(() => props.compact ?? props.size === 'badge');
</script>

<template>
  <span
    data-slot="bilingual-enum"
    :title="isCompact && pair.en ? pair.en : undefined"
    :class="cn(
      'min-w-0',
      isCompact && 'inline-flex max-w-full items-center',
      !isCompact && size === 'large' && 'flex w-full flex-col gap-1',
      !isCompact && size === 'inline' && 'inline-flex flex-wrap items-baseline gap-x-1.5',
      props.class,
    )"
    :aria-label="pair.en ? `${pair.zh}（${pair.en}）` : pair.zh"
  >
    <span
      :class="cn(
        'min-w-0 truncate font-semibold tracking-tight',
        size === 'large' && !isCompact && 'text-2xl leading-tight sm:text-3xl',
        (size === 'badge' || isCompact) && 'text-xs',
        size === 'inline' && !isCompact && 'text-sm',
      )"
    >{{ pair.zh }}</span>
    <span
      v-if="pair.en && !isCompact"
      :class="cn(
        'min-w-0 break-words font-normal tracking-wide text-muted-foreground',
        size === 'large' && 'text-xs sm:text-sm',
        size === 'inline' && 'text-xs',
      )"
    >{{ pair.en }}</span>
  </span>
</template>
