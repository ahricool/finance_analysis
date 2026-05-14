<script setup lang="ts">
import { cn } from '@/utils/cn';

withDefaults(
  defineProps<{
    class?: string;
  }>(),
  {
    class: '',
  },
);
</script>

<template>
  <div
    :class="
      cn(
        'glass-panel flex flex-col gap-3 px-4 py-3 md:flex-row md:items-center md:justify-between',
        $props.class,
      )
    "
  >
    <div class="flex flex-wrap items-center gap-2">
      <slot name="left" />
    </div>
    <div class="flex flex-wrap items-center gap-2 md:justify-end">
      <slot name="right" />
    </div>
  </div>
</template>
