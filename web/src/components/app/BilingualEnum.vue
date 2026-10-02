<script setup lang="ts">
import { computed } from 'vue';
import { enumLabel } from '@/i18n/labels';
import { cn } from '@/utils/cn';

const props = withDefaults(defineProps<{
  value?: string | null;
  /** large | badge | inline */
  size?: 'large' | 'badge' | 'inline';
  class?: string;
}>(), {
  size: 'inline',
});

const pair = computed(() => enumLabel(props.value));
</script>

<template>
  <span
    data-slot="bilingual-enum"
    :class="cn(
      'inline-flex min-w-0',
      size === 'large' && 'flex-col gap-1',
      size === 'badge' && 'flex-col items-start gap-0.5 leading-tight',
      size === 'inline' && 'flex-wrap items-baseline gap-x-1.5',
      props.class,
    )"
    :aria-label="pair.en ? `${pair.zh}（${pair.en}）` : pair.zh"
  >
    <span
      :class="cn(
        'min-w-0 break-words font-semibold tracking-tight',
        size === 'large' && 'text-2xl leading-tight sm:text-3xl',
        size === 'badge' && 'text-sm',
        size === 'inline' && 'text-sm',
      )"
    >{{ pair.zh }}</span>
    <span
      v-if="pair.en"
      :class="cn(
        'min-w-0 break-words font-normal tracking-wide text-muted-foreground',
        size === 'large' && 'text-xs sm:text-sm',
        size === 'badge' && 'text-[10px]',
        size === 'inline' && 'text-xs',
      )"
    >{{ pair.en }}</span>
  </span>
</template>
