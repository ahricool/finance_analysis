<script setup lang="ts">
import { Activity, FlaskConical, Sigma, Star, Wallet } from 'lucide-vue-next';
import { computed } from 'vue';
import { RouterLink, RouterView, useRoute } from 'vue-router';

type MarketTab = 'watch-list' | 'holdings' | 'signals' | 'backtests' | 'quant';

const route = useRoute();
const navItems = [
  { key: 'watch-list' as const, label: '自选股', icon: Star, to: '/market/watch-list' },
  { key: 'holdings' as const, label: '持仓股', icon: Wallet, to: '/market/holdings' },
  { key: 'signals' as const, label: '信号评估', icon: Activity, to: '/market/signals' },
  { key: 'backtests' as const, label: '策略回测', icon: FlaskConical, to: '/market/backtests' },
  { key: 'quant' as const, label: '量化研究', icon: Sigma, to: '/market/quant' },
];
const quantNavItems = [
  { label: '总览', to: '/market/quant' },
  { label: '模型选股', to: '/market/quant/signals' },
  { label: '模型运行', to: '/market/quant/models' },
  { label: '事件', to: '/market/quant/events' },
  { label: '组合建议', to: '/market/quant/portfolios' },
];

const activeTab = computed<MarketTab>(() => {
  if (route.path.startsWith('/market/backtests')) return 'backtests';
  if (route.path.startsWith('/market/quant')) return 'quant';
  if (route.path.endsWith('/holdings')) return 'holdings';
  if (route.path.endsWith('/signals')) return 'signals';
  return 'watch-list';
});

function navClass(key: MarketTab): string[] {
  return [
    'flex h-11 min-w-0 items-center justify-center gap-2 rounded-xl px-2 text-sm font-medium transition-colors lg:w-full lg:justify-start lg:px-3',
    activeTab.value === key
      ? 'bg-primary/12 text-primary'
      : 'text-secondary-text hover:bg-hover hover:text-foreground',
  ];
}
</script>

<template>
  <div class="space-y-5">
    <header class="flex flex-col gap-1">
      <h1 class="text-xl font-semibold text-foreground">
        市场
      </h1>
      <p class="text-sm text-muted-text">
        管理自选股、持仓股，查看历史信号并执行策略回测。
      </p>
    </header>

    <nav
      class="grid grid-cols-2 gap-1 rounded-2xl border border-border/70 bg-card/94 p-2 shadow-soft-card backdrop-blur-sm min-[360px]:grid-cols-3 sm:grid-cols-5 lg:hidden"
      aria-label="市场页面导航"
      data-testid="market-mobile-nav"
    >
      <RouterLink
        v-for="item in navItems"
        :key="item.key"
        :to="item.to"
        :class="navClass(item.key)"
      >
        <component
          :is="item.icon"
          class="h-4 w-4 shrink-0"
        />
        <span class="whitespace-nowrap">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <div class="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
      <aside
        class="hidden h-fit space-y-1 rounded-2xl border border-border/70 bg-card/94 p-2 shadow-soft-card backdrop-blur-sm lg:block"
        data-testid="market-desktop-nav"
      >
        <RouterLink
          v-for="item in navItems"
          :key="item.key"
          :to="item.to"
          :class="navClass(item.key)"
        >
          <component
            :is="item.icon"
            class="h-4 w-4 shrink-0"
          />
          <span class="truncate">{{ item.label }}</span>
        </RouterLink>
      </aside>

      <section class="min-w-0">
        <nav v-if="activeTab === 'quant'" class="mb-4 flex flex-wrap gap-2" aria-label="量化研究导航">
          <RouterLink
            v-for="item in quantNavItems"
            :key="item.to"
            :to="item.to"
            class="whitespace-nowrap rounded-lg px-3 py-2 text-xs text-secondary-text hover:bg-hover"
            :class="route.path === item.to || (item.to !== '/market/quant' && route.path.startsWith(`${item.to}/`)) ? 'bg-primary/12 text-primary' : ''"
          >
            {{ item.label }}
          </RouterLink>
        </nav>
        <RouterView />
      </section>
    </div>
  </div>
</template>
