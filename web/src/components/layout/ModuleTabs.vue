<script setup lang="ts">
import type { Component } from 'vue';
import { RouterLink, type RouteLocationRaw } from 'vue-router';

export type ModuleTab = { key: string; label: string; icon?: Component; to: RouteLocationRaw };
defineProps<{ items: ModuleTab[]; activeKey: string; label: string }>();
defineEmits<{ navigate: [] }>();
</script>

<template>
  <nav
    :aria-label="label"
    class="flex flex-col gap-1 rounded-xl border border-border bg-card p-2"
    data-testid="module-tabs"
  >
    <RouterLink
      v-for="item in items"
      :key="item.key"
      :to="item.to"
      :aria-current="activeKey === item.key ? 'page' : undefined"
      :data-state="activeKey === item.key ? 'active' : 'inactive'"
      class="flex min-h-10 items-center gap-2 rounded-md border border-transparent px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      :class="activeKey === item.key && 'border-brand/25 bg-brand/10 font-medium text-foreground'"
      @click="$emit('navigate')"
    >
      <component
        :is="item.icon"
        v-if="item.icon"
        class="size-4 shrink-0"
        aria-hidden="true"
      />
      {{ item.label }}
    </RouterLink>
  </nav>
</template>
