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
        'pointer-events-none fixed bottom-5 right-5 z-50 flex w-[360px] max-w-[calc(100vw-24px)] flex-col gap-3',
        $props.class,
      )
    "
  >
    <slot />
  </div>
</template>
