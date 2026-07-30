<script setup lang="ts">
import type { HTMLAttributes } from 'vue';
import { cn } from '@/utils/cn';
const props = defineProps<{ class?: HTMLAttributes['class'] }>();
</script>
<template>
  <div
    data-slot="empty"
    :class="cn('flex w-full min-w-0 flex-1 flex-col items-center justify-center gap-4 rounded-lg border border-dashed p-8 text-center text-balance sm:p-12', props.class)"
  >
    <slot />
  </div>
</template>
