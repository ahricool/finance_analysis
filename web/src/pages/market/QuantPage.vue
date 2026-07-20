<script setup lang="ts">
import { RouterLink, RouterView, useRoute } from 'vue-router';

const route = useRoute();
const navItems = [
  { label: '总览', to: '/market/quant' },
  { label: '模型选股', to: '/market/quant/signals' },
  { label: '模型运行', to: '/market/quant/models' },
  { label: '事件', to: '/market/quant/events' },
  { label: '组合建议', to: '/market/quant/portfolios' },
];

function isActive(to: string): boolean {
  return route.path === to || (to !== '/market/quant' && route.path.startsWith(`${to}/`));
}
</script>

<template>
  <div class="space-y-4">
    <nav
      class="flex flex-wrap gap-1 rounded-2xl border border-border/70 bg-card/94 p-1.5 shadow-soft-card backdrop-blur-sm"
      aria-label="量化研究导航"
    >
      <RouterLink
        v-for="item in navItems"
        :key="item.to"
        :to="item.to"
        class="whitespace-nowrap rounded-xl px-3 py-2 text-sm font-medium text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
        :class="isActive(item.to) ? 'bg-primary/12 text-primary' : ''"
      >
        {{ item.label }}
      </RouterLink>
    </nav>
    <RouterView />
  </div>
</template>
