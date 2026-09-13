<script setup lang="ts">
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import ModuleTabs from '@/components/layout/ModuleTabs.vue';
import { Button } from '@/components/ui/button';
import { useQuantMarket } from '@/composables/useQuantMarket';
import { BarChart3, Bot, BriefcaseBusiness, Database, LayoutDashboard } from 'lucide-vue-next';
import { computed, ref, watch } from 'vue';
import { RouterView, useRoute, useRouter } from 'vue-router';

type QuantTab = 'dashboard' | 'signals' | 'datasets' | 'models' | 'portfolios';

const route = useRoute();
const router = useRouter();
const { market, setMarket, marketQuery } = useQuantMarket();
const scopeDescription = computed(() =>
  market.value === 'US' ? '当前范围：标普500' : '当前范围：沪深300',
);
const selectedDate = ref('');
const baseNavItems = [
  { key: 'dashboard' as const, label: '总览', icon: LayoutDashboard, path: '/research/quant' },
  { key: 'signals' as const, label: '模型选股', icon: BarChart3, path: '/research/quant/signals' },
  { key: 'datasets' as const, label: '数据集', icon: Database, path: '/research/quant/datasets' },
  { key: 'models' as const, label: '模型运行', icon: Bot, path: '/research/quant/models' },
  {
    key: 'portfolios' as const,
    label: '目标组合',
    icon: BriefcaseBusiness,
    path: '/research/quant/portfolios',
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
const marketDateQuery = computed(() => route.query.tradeDate);

function toDateString(queryValue: unknown): string {
  if (queryValue == null) return '';
  if (typeof queryValue === 'string') return queryValue;
  if (Array.isArray(queryValue)) return queryValue[0] ?? '';
  return String(queryValue);
}

function setTradeDate(value: string) {
  const nextQuery = { ...route.query };
  if (value) {
    nextQuery.tradeDate = value;
  } else {
    delete nextQuery.tradeDate;
  }
  void router.push({ query: nextQuery });
}

watch(marketDateQuery, (queryValue) => {
  const normalized = toDateString(queryValue);
  if (selectedDate.value !== normalized) {
    selectedDate.value = normalized;
  }
}, { immediate: true });

const activeTab = computed<QuantTab>(() => {
  const path = route.path;
  if (path.startsWith('/research/quant/signals')) return 'signals';
  if (path.startsWith('/research/quant/datasets')) return 'datasets';
  if (path.startsWith('/research/quant/models')) return 'models';
  if (path.startsWith('/research/quant/portfolios')) return 'portfolios';
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
        <div class="w-56">
          <AppDatePicker
            label="交易日"
            v-model="selectedDate"
            data-testid="quant-trade-date"
            class="w-full"
            @update:model-value="setTradeDate"
          />
        </div>
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
