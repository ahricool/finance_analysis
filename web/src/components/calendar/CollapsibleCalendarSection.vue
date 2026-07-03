<script setup lang="ts">
import { ChevronDown } from 'lucide-vue-next';

defineProps<{
  title: string;
  description: string;
  count: number;
  open: boolean;
  loading?: boolean;
  testId: string;
}>();

defineEmits<{
  'update:open': [open: boolean];
}>();
</script>

<template>
  <section class="overflow-hidden rounded-2xl border border-border/60 bg-card shadow-soft-card" :data-testid="testId">
    <div class="flex items-stretch justify-between gap-2 px-4 py-3">
      <button
        type="button"
        class="flex min-w-0 flex-1 items-center gap-3 text-left"
        :aria-expanded="open"
        :aria-controls="`${testId}-content`"
        @click="$emit('update:open', !open)"
      >
        <ChevronDown
          class="h-4 w-4 shrink-0 text-secondary-text transition-transform duration-200"
          :class="open ? 'rotate-180' : ''"
        />
        <span class="min-w-0 flex-1">
          <span class="flex flex-wrap items-center gap-2">
            <span class="text-sm font-semibold text-foreground">{{ title }}</span>
            <span class="rounded-full bg-hover px-2 py-0.5 text-xs font-medium tabular-nums text-secondary-text">
              {{ loading ? '…' : count }}
            </span>
          </span>
          <span class="mt-0.5 block truncate text-xs text-muted-text">{{ description }}</span>
        </span>
      </button>
      <div class="flex shrink-0 items-center" @click.stop>
        <slot name="actions" />
      </div>
    </div>

    <div v-show="open" :id="`${testId}-content`" class="border-t border-border/50 p-4">
      <slot />
    </div>
  </section>
</template>
