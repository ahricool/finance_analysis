<script setup lang="ts">
import { cn } from '@/utils/cn';

type InlineAlertVariant = 'info' | 'success' | 'warning' | 'danger';

const props = withDefaults(
  defineProps<{
    title?: string;
    variant?: InlineAlertVariant;
    class?: string;
  }>(),
  {
    variant: 'info',
    class: '',
  },
);

const variantStyles: Record<InlineAlertVariant, string> = {
  info: 'border-cyan/20 bg-cyan/10 text-cyan',
  success: 'border-success/20 bg-success/10 text-success',
  warning: 'border-warning/20 bg-warning/10 text-warning',
  danger:
    'border-[hsl(var(--color-danger-alert-border)/0.3)] bg-[hsl(var(--color-danger-alert-bg)/0.1)] text-[hsl(var(--color-danger-alert-text))]',
};
</script>

<template>
  <div
    role="alert"
    :class="cn('rounded-2xl border px-4 py-3 shadow-soft-card', variantStyles[variant], props.class)"
  >
    <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
      <div>
        <p v-if="title" class="text-sm font-semibold">{{ title }}</p>
        <div :class="cn('text-sm', title ? 'mt-1 opacity-90' : 'opacity-90')">
          <slot />
        </div>
      </div>
      <div v-if="$slots.action" class="shrink-0">
        <slot name="action" />
      </div>
    </div>
  </div>
</template>
