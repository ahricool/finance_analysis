<script setup lang="ts">
import type { NavDestination } from '@/config/mainNav';
import { RouterLink } from 'vue-router';

defineProps<{ items: NavDestination[]; activeKey: string; label: string }>();
</script>

<template>
  <nav
    :aria-label="label"
    class="module-sidebar flex flex-col gap-1 overflow-x-hidden overflow-y-auto rounded-xl border border-border bg-card p-1.5 shadow-sm"
    data-testid="module-tabs"
  >
    <RouterLink
      v-for="item in items"
      :key="item.key"
      :to="item.to"
      :aria-label="item.label"
      :aria-current="activeKey === item.key ? 'page' : undefined"
      :data-state="activeKey === item.key ? 'active' : 'inactive'"
      class="flex min-h-10 shrink-0 items-center gap-2 rounded-md border border-transparent px-2.5 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      :class="activeKey === item.key && 'border-brand/25 bg-brand/10 font-medium text-foreground'"
    >
      <component
        :is="item.icon"
        class="size-4 shrink-0"
        aria-hidden="true"
      />
      <span class="module-sidebar-label whitespace-nowrap">{{ item.label }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.module-sidebar {
  width: 100%;
  scrollbar-width: thin;
}

.module-sidebar-label {
  visibility: hidden;
}

.module-sidebar:has(:focus-visible) {
  width: 12rem;
}

.module-sidebar:has(:focus-visible) .module-sidebar-label {
  visibility: visible;
}

@media (hover: hover) {
  .module-sidebar:hover {
    width: 12rem;
  }

  .module-sidebar:hover .module-sidebar-label {
    visibility: visible;
  }
}

@media (prefers-reduced-motion: no-preference) {
  .module-sidebar {
    transition: width 150ms ease;
  }
}
</style>
