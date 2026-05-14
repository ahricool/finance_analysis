<script setup lang="ts">
import { cn } from '@/utils/cn';

const props = withDefaults(
  defineProps<{
    title: string;
    description?: string;
    class?: string;
  }>(),
  { class: '' },
);
</script>

<template>
  <div
    :class="
      cn(
        'rounded-[1.5rem] border settings-border bg-card/94 p-5 shadow-soft-card-strong backdrop-blur-sm',
        props.class,
      )
    "
  >
    <div class="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div class="min-w-0 space-y-1">
        <h2 class="text-sm font-semibold tracking-tight text-foreground uppercase tracking-wider">
          {{ title }}
        </h2>
        <p v-if="description" class="text-xs leading-6 text-muted-text">{{ description }}</p>
      </div>
      <div v-if="$slots.actions" class="flex shrink-0 items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
    <div class="space-y-5">
      <slot />
    </div>
  </div>
</template>
