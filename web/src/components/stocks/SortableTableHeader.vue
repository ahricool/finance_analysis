<script setup lang="ts">
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-vue-next';

withDefaults(defineProps<{
  label: string;
  active?: boolean;
  direction?: 'asc' | 'desc';
  align?: 'left' | 'right';
}>(), {
  active: false,
  direction: 'asc',
  align: 'left',
});

defineEmits<{
  sort: [];
}>();
</script>

<template>
  <th
    class="whitespace-nowrap px-4 py-3 font-medium"
    :class="align === 'right' ? 'text-right' : 'text-left'"
    :aria-sort="active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'"
  >
    <button
      type="button"
      class="flex items-center gap-1.5 whitespace-nowrap transition-colors hover:text-foreground"
      :class="align === 'right' ? 'ml-auto' : ''"
      @click="$emit('sort')"
    >
      {{ label }}
      <ArrowUp v-if="active && direction === 'asc'" class="h-3.5 w-3.5" />
      <ArrowDown v-else-if="active" class="h-3.5 w-3.5" />
      <ArrowUpDown v-else class="h-3.5 w-3.5 opacity-50" />
    </button>
  </th>
</template>
