<script setup lang="ts">
import { cn } from '@/utils/cn';

withDefaults(
  defineProps<{
    title: string;
    description?: string;
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
        'rounded-2xl border border-dashed border-border/60 bg-card/50 px-6 py-10 text-center shadow-soft-card',
        $props.class,
      )
    "
  >
    <div v-if="$slots.icon" class="mb-4 flex justify-center text-cyan">
      <slot name="icon" />
    </div>
    <h3 class="text-base font-semibold text-foreground">{{ title }}</h3>
    <p v-if="description" class="mx-auto mt-2 max-w-md text-sm text-secondary-text">
      {{ description }}
    </p>
    <div v-if="$slots.action" class="mt-5 flex justify-center">
      <slot name="action" />
    </div>
  </div>
</template>
