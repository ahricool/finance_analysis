<script setup lang="ts">
import ModuleTabs from '@/components/layout/ModuleTabs.vue';
import { Button } from '@/components/ui/button';
import { useQuantMarket } from '@/composables/useQuantMarket';
import { BarChart3, Bot, BriefcaseBusiness, Database, LayoutDashboard } from 'lucide-vue-next';
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';

type QuantTab = 'dashboard' | 'signals' | 'datasets' | 'models' | 'portfolios';

const route = useRoute();
const { market, setMarket, marketQuery } = useQuantMarket();
const scopeDescription = computed(() =>
  market.value === 'US' ? '当前范围：标普500' : '当前范围：沪深300',
);
const baseNavItems = [
  { key: 'dashboard' as const, label: '总览', icon: LayoutDashboard, path: '/market/quant' },
  { key: 'signals' as const, label: '模型选股', icon: BarChart3, path: '/market/quant/signals' },
  { key: 'datasets' as const, label: '数据集', icon: Database, path: '/market/quant/datasets' },
  { key: 'models' as const, label: '模型运行', icon: Bot, path: '/market/quant/models' },
  {
    key: 'portfolios' as const,
    label: '组合建议',
    icon: BriefcaseBusiness,
    path: '/market/quant/portfolios',
  },
];
const navItems = computed(() =>
  baseNavItems.map((item) => ({
    key: item.key,
    label: item.label,
    icon: item.icon,
    to: { path: item.path, query: marketQuery() },
  })),
);
const activeTab = computed<QuantTab>(() => {
  const path = route.path;
  if (path.startsWith('/market/quant/signals')) return 'signals';
  if (path.startsWith('/market/quant/datasets')) return 'datasets';
  if (path.startsWith('/market/quant/models')) return 'models';
  if (path.startsWith('/market/quant/portfolios')) return 'portfolios';
  return 'dashboard';
});
</script>

<template>
  <div class="min-w-0 space-y-4">
    <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <ModuleTabs
        :items="navItems"
        :active-key="activeTab"
        label="量化研究导航"
      />
      <div class="flex items-center gap-3">
        <p
          class="text-xs text-muted-foreground"
          data-testid="quant-scope-description"
        >
          {{ scopeDescription }}
        </p>
        <div
          class="flex items-center gap-1 rounded-lg bg-muted p-1"
          role="radiogroup"
          aria-label="量化市场"
          data-testid="quant-market-switcher"
        >
          <Button
            v-for="option in [{ value: 'US', label: '美股' }, { value: 'CN', label: 'A股' }]"
            :key="option.value"
            size="sm"
            :variant="market === option.value ? 'default' : 'ghost'"
            role="radio"
            :aria-checked="market === option.value"
            @click="setMarket(option.value as 'US' | 'CN')"
          >
            {{ option.label }}
          </Button>
        </div>
      </div>
    </div>
    <section class="min-w-0">
      <RouterView />
    </section>
  </div>
</template>
