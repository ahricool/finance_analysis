<script setup lang="ts">
import { cn } from '@/utils/cn';

withDefaults(
  defineProps<{
    eyebrow?: string;
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
  <header :class="cn('glass-panel-lg relative overflow-hidden px-5 py-5 md:px-7 md:py-6', $props.class)">
    <div
      class="pointer-events-none absolute -right-14 -top-20 h-40 w-40 rounded-full bg-primary/10 blur-3xl"
      aria-hidden="true"
    />
    <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div>
        <span v-if="eyebrow" class="label-uppercase">{{ eyebrow }}</span>
        <h1 class="mt-3 max-w-3xl font-display text-[2rem] leading-[1.08] text-foreground md:text-[2.75rem]">
          {{ title }}
        </h1>
        <p v-if="description" class="mt-3 max-w-2xl text-sm leading-6 text-secondary-text md:text-base md:leading-7">
          {{ description }}
        </p>
      </div>
      <div v-if="$slots.actions" class="flex flex-wrap items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
  </header>
</template>
