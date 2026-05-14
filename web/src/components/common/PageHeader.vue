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
  <header :class="cn('glass-panel-lg px-5 py-5', $props.class)">
    <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div>
        <span v-if="eyebrow" class="label-uppercase">{{ eyebrow }}</span>
        <h1 class="mt-2 text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
          {{ title }}
        </h1>
        <p v-if="description" class="mt-2 max-w-2xl text-sm text-secondary-text md:text-base">
          {{ description }}
        </p>
      </div>
      <div v-if="$slots.actions" class="flex flex-wrap items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
  </header>
</template>
