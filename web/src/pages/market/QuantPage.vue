<script setup lang="ts">
import { computed } from 'vue';
import { RouterLink, RouterView, useRoute } from 'vue-router';
import { useQuantMarket } from '@/composables/useQuantMarket';

const route = useRoute();
const { market, setMarket, marketQuery } = useQuantMarket();
const scopeDescription = computed(() => (
  market.value === 'US' ? '当前范围：标普500 + 美股自选' : '当前范围：沪深300 + A股自选'
));
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
    <div class="flex flex-wrap items-center justify-between gap-3">
      <nav
        class="flex flex-wrap gap-1 rounded-2xl border border-border/70 bg-card/94 p-1.5 shadow-soft-card backdrop-blur-sm"
        aria-label="量化研究导航"
      >
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="{ path: item.to, query: marketQuery() }"
          class="whitespace-nowrap rounded-xl px-3 py-2 text-sm font-medium text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
          :class="isActive(item.to) ? 'bg-primary/12 text-primary' : ''"
        >
          {{ item.label }}
        </RouterLink>
      </nav>
      <div
        class="inline-flex min-w-[132px] rounded-xl border border-border bg-card p-1"
        role="radiogroup"
        aria-label="量化市场"
        data-testid="quant-market-switcher"
      >
        <button
          v-for="option in [{ value: 'US', label: '美股' }, { value: 'CN', label: 'A股' }]"
          :key="option.value"
          type="button"
          role="radio"
          :aria-checked="market === option.value"
          class="min-h-9 flex-1 rounded-lg px-3 text-sm font-medium transition-colors"
          :class="market === option.value ? 'bg-primary text-primary-foreground' : 'text-secondary-text hover:bg-hover'"
          @click="setMarket(option.value as 'US' | 'CN')"
        >
          {{ option.label }}
        </button>
      </div>
    </div>
    <p class="px-1 text-xs text-secondary-text" data-testid="quant-scope-description">
      {{ scopeDescription }}
    </p>
    <RouterView />
  </div>
</template>
