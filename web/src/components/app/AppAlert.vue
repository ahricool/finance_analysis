<script setup lang="ts">
import { computed } from 'vue';
import { cn } from '@/lib/utils';

type Tone = 'info' | 'success' | 'warning' | 'destructive';

const props = withDefaults(
  defineProps<{
    title?: string;
    variant?: Tone;
    class?: string;
  }>(),
  {
    title: '',
    variant: 'info',
    class: '',
  },
);

const toneClass = computed(
  () =>
    ({
      info: 'border-primary/25 bg-primary/8 text-foreground',
      success: 'border-success/25 bg-success/8 text-success',
      warning: 'border-warning/25 bg-warning/8 text-warning',
      destructive: 'border-destructive/25 bg-destructive/8 text-destructive',
    })[props.variant],
);
</script>
<template>
  <div
    role="alert"
    :class="cn('rounded-xl border p-4 text-sm', toneClass, props.class)"
  >
    <div class="flex flex-col gap-3 sm:flex-row sm:justify-between">
      <div>
        <p
          v-if="title"
          class="font-semibold"
        >
          {{ title }}
        </p>
        <div :class="title && 'mt-1'">
          <slot />
        </div>
      </div>
      <div v-if="$slots.action">
        <slot name="action" />
      </div>
    </div>
  </div>
</template>
