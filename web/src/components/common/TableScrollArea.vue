<script setup lang="ts">
import { useHorizontalWheelScroll } from '@/composables/useHorizontalWheelScroll';
import { cn } from '@/utils/cn';

const props = withDefaults(
  defineProps<{
    class?: string;
    bordered?: boolean;
  }>(),
  {
    bordered: true,
  },
);

const { onWheel } = useHorizontalWheelScroll();
</script>

<template>
  <div
    :class="
      cn(
        'table-scroll-x',
        props.bordered && 'rounded-2xl border border-border/70 bg-card/94 shadow-soft-card',
        props.class,
      )
    "
    @wheel="onWheel"
  >
    <slot />
  </div>
</template>
