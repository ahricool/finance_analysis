<script setup lang="ts">
import { cn } from '@/utils/cn';
import { useAttrs, computed } from 'vue';

type StatusDotTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

const TONE_STYLES: Record<StatusDotTone, string> = {
  success: 'bg-success shadow-[0_0_0_3px_hsl(var(--success)/0.12)]',
  warning: 'bg-warning shadow-[0_0_0_3px_hsl(var(--warning)/0.14)]',
  danger: 'bg-danger shadow-[0_0_0_3px_hsl(var(--destructive)/0.12)]',
  info: 'bg-cyan shadow-[0_0_0_3px_hsl(var(--primary)/0.12)]',
  neutral: 'bg-muted-text shadow-[0_0_0_3px_hsl(var(--muted-text)/0.12)]',
};

const props = withDefaults(
  defineProps<{
    tone?: StatusDotTone;
    pulse?: boolean;
    class?: string;
  }>(),
  {
    tone: 'neutral',
    pulse: false,
    class: '',
  },
);

const attrs = useAttrs();

const hasAccessibleLabel = computed(
  () => typeof attrs['aria-label'] === 'string' && (attrs['aria-label'] as string).length > 0,
);
</script>

<template>
  <span
    :aria-hidden="hasAccessibleLabel ? undefined : true"
    :class="
      cn(
        'inline-flex h-2.5 w-2.5 shrink-0 rounded-full',
        TONE_STYLES[tone],
        pulse ? 'animate-pulse' : '',
        props.class,
      )
    "
    v-bind="attrs"
  />
</template>
