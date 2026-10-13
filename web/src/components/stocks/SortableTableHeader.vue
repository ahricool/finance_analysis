<script setup lang="ts">
import type { HTMLAttributes } from 'vue';
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-vue-next';
import BilingualLabel from '@/components/app/BilingualLabel.vue';
import MetricHint from '@/components/app/MetricHint.vue';
import { metricLabel } from '@/i18n/labels';
import { metricHint } from '@/utils/metricHints';
import { TableHead } from '@/components/ui/table';
import { cn } from '@/utils/cn';

const props = withDefaults(defineProps<{
  /** Glossary key from metricLabels, or raw Chinese. */
  label: string;
  description?: string;
  scope?: string;
  active?: boolean;
  direction?: 'asc' | 'desc';
  align?: 'left' | 'right';
  class?: HTMLAttributes['class'];
}>(), {
  description: undefined,
  scope: undefined,
  active: false,
  direction: 'asc',
  align: 'left',
  class: undefined,
});

defineEmits<{
  sort: [];
}>();
</script>

<template>
  <TableHead
    :class="cn('whitespace-nowrap px-4 py-3 font-medium', props.class, props.align === 'right' ? 'text-right' : 'text-left')"
    :aria-sort="active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'"
  >
    <div class="flex min-w-max items-center gap-1">
      <button
        type="button"
        class="flex shrink-0 items-center gap-1.5 transition-colors hover:text-foreground"
        :class="props.align === 'right' ? 'ml-auto' : ''"
        @click="$emit('sort')"
      >
        <BilingualLabel
          :label="label"
          compact
        />
        <ArrowUp
          v-if="active && direction === 'asc'"
          class="h-3.5 w-3.5 shrink-0"
        />
        <ArrowDown
          v-else-if="active"
          class="h-3.5 w-3.5 shrink-0"
        />
        <ArrowUpDown
          v-else
          class="h-3.5 w-3.5 shrink-0 opacity-50"
        />
      </button>
      <MetricHint
        v-if="description ?? metricHint(scope, label)"
        :label="metricLabel(label).zh"
        :description="(description ?? metricHint(scope, label))!"
      />
    </div>
  </TableHead>
</template>
