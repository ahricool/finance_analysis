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
        'sticky bottom-4 z-20 rounded-2xl border border-subtle bg-card/85 p-3 shadow-soft-card backdrop-blur-md',
        $props.class,
      )
    "
  >
    <div class="flex flex-wrap items-center justify-end gap-2">
      <slot />
    </div>
  </div>
</template>
