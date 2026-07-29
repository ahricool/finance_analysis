<script setup lang="ts">
import type { HTMLAttributes } from 'vue';
import { computed } from 'vue';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

export type AppBadgeVariant = 'default' | 'secondary' | 'outline' | 'destructive' | 'success' | 'warning' | 'info';
const props = withDefaults(defineProps<{ variant?: AppBadgeVariant; class?: HTMLAttributes['class'] }>(), { variant: 'default' });
const baseVariant = computed(() => ['default', 'secondary', 'outline', 'destructive'].includes(props.variant)
  ? props.variant as 'default' | 'secondary' | 'outline' | 'destructive'
  : 'outline');
const semanticClasses: Partial<Record<AppBadgeVariant, string>> = {
  success: 'border-success/25 bg-success/10 text-success',
  warning: 'border-warning/25 bg-warning/10 text-warning',
  info: 'border-primary/25 bg-primary/10 text-primary',
};
const semanticClass = computed(() => semanticClasses[props.variant] ?? '');
</script>

<template><Badge :variant="baseVariant" :class="cn(semanticClass, props.class)"><slot /></Badge></template>
