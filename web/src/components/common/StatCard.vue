<script setup lang="ts">
import { cn } from '@/utils/cn';

const toneStyles = {
  default: 'border-subtle',
  primary: 'border-cyan/18',
  success: 'border-success/18',
  warning: 'border-warning/18',
  danger: 'border-danger/18',
};

withDefaults(
  defineProps<{
    label: string;
    hint?: string;
    tone?: keyof typeof toneStyles;
    class?: string;
  }>(),
  {
    tone: 'default',
    class: '',
  },
);
</script>

<template>
  <div
    :class="
      cn('rounded-2xl border bg-card/75 p-4 shadow-soft-card', toneStyles[tone as keyof typeof toneStyles], $props.class)
    "
  >
    <div class="flex items-start justify-between gap-3">
      <div>
        <p class="text-xs uppercase tracking-[0.22em] text-secondary-text">{{ label }}</p>
        <div class="mt-2 text-2xl font-semibold text-foreground">
          <slot />
        </div>
        <div v-if="hint" class="mt-2 text-sm text-secondary-text">{{ hint }}</div>
      </div>
      <div v-if="$slots.icon" class="text-cyan">
        <slot name="icon" />
      </div>
    </div>
  </div>
</template>
