<script setup lang="ts">
import type { Component } from 'vue';
import type { RouteLocationRaw } from 'vue-router';

export interface SectionNavItem {
  key: string;
  label: string;
  icon: Component;
  to?: RouteLocationRaw;
}

const props = withDefaults(defineProps<{
  items: SectionNavItem[];
  activeKey: string;
  responsive?: boolean;
}>(), {
  responsive: false,
});

const emit = defineEmits<{
  select: [key: string];
}>();

function itemClass(key: string): string[] {
  return [
    'flex h-11 min-w-0 items-center gap-2 rounded-xl text-sm font-medium transition-colors',
    props.responsive
      ? 'justify-center px-2 lg:w-full lg:justify-start lg:px-3'
      : 'w-full justify-start px-3 text-left',
    props.activeKey === key
      ? 'bg-primary/12 text-primary'
      : 'text-secondary-text hover:bg-hover hover:text-foreground',
  ];
}
</script>

<template>
  <template v-for="item in items" :key="item.key">
    <RouterLink
      v-if="item.to"
      :to="item.to"
      :class="itemClass(item.key)"
    >
      <component :is="item.icon" class="h-4 w-4 shrink-0" />
      <span class="truncate">{{ item.label }}</span>
    </RouterLink>
    <button
      v-else
      type="button"
      :aria-current="activeKey === item.key ? 'page' : undefined"
      :class="itemClass(item.key)"
      @click="emit('select', item.key)"
    >
      <component :is="item.icon" class="h-4 w-4 shrink-0" />
      <span class="truncate">{{ item.label }}</span>
    </button>
  </template>
</template>
