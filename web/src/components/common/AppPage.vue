<script setup lang="ts">
import { cn } from '@/utils/cn';

const props = withDefaults(
  defineProps<{
    class?: string;
  }>(),
  { class: '' },
);
</script>

<template>
  <div :class="cn('app-page relative flex min-h-screen flex-1 flex-col overflow-hidden bg-background text-foreground', props.class)">
    <slot />
  </div>
</template>
