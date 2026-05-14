<script setup lang="ts">
import { cn } from '@/utils/cn';
import { computed } from 'vue';

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'history';

const props = withDefaults(
  defineProps<{
    variant?: BadgeVariant;
    size?: 'sm' | 'md';
    glow?: boolean;
    class?: string;
    inlineStyle?: Record<string, string>;
  }>(),
  {
    variant: 'default',
    size: 'sm',
    glow: false,
    class: '',
  },
);

const variantStyles: Record<BadgeVariant, string> = {
  default: 'border-border/55 bg-elevated/75 text-secondary-text',
  success: 'border-success/20 bg-success/10 text-success',
  warning: 'border-warning/20 bg-warning/10 text-warning',
  danger: 'border-danger/20 bg-danger/10 text-danger',
  info: 'border-cyan/30 bg-cyan/12 text-cyan',
  history: 'border-purple/20 bg-purple/10 text-purple',
};

const glowStyles: Record<BadgeVariant, string> = {
  default: '',
  success: 'shadow-success/20',
  warning: 'shadow-warning/20',
  danger: 'shadow-danger/20',
  info: 'shadow-cyan/20',
  history: 'shadow-purple/20',
};

const badgeClass = computed(() =>
  cn(
    'inline-flex items-center gap-1 rounded-full border font-medium backdrop-blur-sm',
    props.size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm',
    variantStyles[props.variant],
    props.glow && `shadow-lg ${glowStyles[props.variant]}`,
    props.class,
  ),
);
</script>

<template>
  <span :class="badgeClass" :style="inlineStyle">
    <slot />
  </span>
</template>
