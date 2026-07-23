<script setup lang="ts">
import SectionNavItems from '@/components/common/SectionNavItems.vue';
import SectionNavPanel from '@/components/common/SectionNavPanel.vue';
import SectionPageHeader from '@/components/common/SectionPageHeader.vue';
import { useQuantMarket } from '@/composables/useQuantMarket';
import { BarChart3, Bot, BriefcaseBusiness, CalendarDays, Database, LayoutDashboard } from 'lucide-vue-next';
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';

type QuantTab = 'dashboard' | 'signals' | 'datasets' | 'models' | 'events' | 'portfolios';

const route = useRoute();
const { market, setMarket, marketQuery } = useQuantMarket();
const scopeDescription = computed(() => (
  market.value === 'US' ? '当前范围：标普500' : '当前范围：沪深300'
));
const baseNavItems = [
  { key: 'dashboard' as const, label: '总览', icon: LayoutDashboard, path: '/market/quant' },
  { key: 'signals' as const, label: '模型选股', icon: BarChart3, path: '/market/quant/signals' },
  { key: 'datasets' as const, label: '数据集', icon: Database, path: '/market/quant/datasets' },
  { key: 'models' as const, label: '模型运行', icon: Bot, path: '/market/quant/models' },
  { key: 'events' as const, label: '事件', icon: CalendarDays, path: '/market/quant/events' },
  { key: 'portfolios' as const, label: '组合建议', icon: BriefcaseBusiness, path: '/market/quant/portfolios' },
];
const navItems = computed(() => baseNavItems.map((item) => ({
  key: item.key,
  label: item.label,
  icon: item.icon,
  to: { path: item.path, query: marketQuery() },
})));
const activeTab = computed<QuantTab>(() => {
  const path = route.path;
  if (path.startsWith('/market/quant/signals')) return 'signals';
  if (path.startsWith('/market/quant/datasets')) return 'datasets';
  if (path.startsWith('/market/quant/models')) return 'models';
  if (path.startsWith('/market/quant/events')) return 'events';
  if (path.startsWith('/market/quant/portfolios')) return 'portfolios';
  return 'dashboard';
});

</script>

<template>
  <div class="space-y-5">
    <SectionPageHeader
      title="量化研究"
      description="管理量化数据集、模型训练、选股信号与组合建议。"
    >
      <div class="mt-2 flex flex-wrap items-center justify-between gap-3">
        <p class="text-xs text-secondary-text" data-testid="quant-scope-description">
          {{ scopeDescription }}
        </p>
        <div
          class="inline-flex min-w-[132px] rounded-xl border border-border/70 bg-card/94 p-1 shadow-soft-card"
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
            class="h-9 flex-1 rounded-lg px-3 text-sm font-medium transition-colors"
            :class="market === option.value ? 'bg-primary text-primary-foreground' : 'text-secondary-text hover:bg-hover hover:text-foreground'"
            @click="setMarket(option.value as 'US' | 'CN')"
          >
            {{ option.label }}
          </button>
        </div>
      </div>
    </SectionPageHeader>

    <nav
      class="grid grid-cols-2 gap-1 rounded-2xl border border-border/70 bg-card/94 p-2 shadow-soft-card backdrop-blur-sm sm:grid-cols-3 lg:hidden"
      aria-label="量化研究导航"
      data-testid="quant-mobile-nav"
    >
      <SectionNavItems :items="navItems" :active-key="activeTab" responsive />
    </nav>

    <div class="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
      <SectionNavPanel
        class="hidden lg:block"
        data-testid="quant-desktop-nav"
        :items="navItems"
        :active-key="activeTab"
        responsive
      />

      <section class="min-w-0">
        <RouterView />
      </section>
    </div>
  </div>
</template>
