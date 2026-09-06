<script setup lang="ts">
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-vue-next';
import IndicatorLabel from '@/components/app/IndicatorHelpLabel.vue';
import { TableHead } from '@/components/ui/table';

withDefaults(defineProps<{
  label: string;
  description?: string;
  active?: boolean;
  direction?: 'asc' | 'desc';
  align?: 'left' | 'right';
}>(), {
  description: undefined,
  active: false,
  direction: 'asc',
  align: 'left',
});

defineEmits<{
  sort: [];
}>();
</script>

<template>
  <TableHead
    class="whitespace-nowrap px-4 py-3 font-medium"
    :class="align === 'right' ? 'text-right' : 'text-left'"
    :aria-sort="active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'"
  >
    <div class="flex items-center gap-1">
      <button
        type="button"
        class="flex items-center gap-1.5 whitespace-nowrap transition-colors hover:text-foreground"
        :class="align === 'right' ? 'ml-auto' : ''"
        @click="$emit('sort')"
      >
        {{ label }}
        <ArrowUp
          v-if="active && direction === 'asc'"
          class="h-3.5 w-3.5"
        />
        <ArrowDown
          v-else-if="active"
          class="h-3.5 w-3.5"
        />
        <ArrowUpDown
          v-else
          class="h-3.5 w-3.5 opacity-50"
        />
      </button>
      <IndicatorLabel
        v-if="description"
        :label="label"
        :description="description"
        class="[&>span:first-child]:hidden"
      />
    </div>
  </TableHead>
</template>
