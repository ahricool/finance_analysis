<script setup lang="ts">
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import ResearchMarketToggle from '@/components/research/ResearchMarketToggle.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import ModuleTabs from '@/components/layout/ModuleTabs.vue';
import { useQuantMarket } from '@/composables/useQuantMarket';
import { BarChart3, Bot, BriefcaseBusiness, Database, LayoutDashboard } from 'lucide-vue-next';
import { computed, ref, watch } from 'vue';
import { RouterView, useRoute } from 'vue-router';

type QuantTab = 'dashboard' | 'signals' | 'datasets' | 'models' | 'portfolios';

const route = useRoute();
const { market, setMarket, marketQuery, tradeDate, setTradeDate } = useQuantMarket();
const scopeDescription = computed(() =>
  market.value === 'US' ? '当前范围：标普500' : '当前范围：沪深300',
);
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
const activeTab = computed<QuantTab>(() => {
  const path = route.path;
  if (path.startsWith('/research/quant/signals')) return 'signals';
  if (path.startsWith('/research/quant/datasets')) return 'datasets';
  if (path.startsWith('/research/quant/models')) return 'models';
  if (path.startsWith('/research/quant/portfolios')) return 'portfolios';
  return 'dashboard';
});
const availableDates = ref<string[]>([]);
const datesLoading = ref(false);
const datesError = ref<ParsedApiError | null>(null);
const signalCode = computed(() => typeof route.params.code === 'string' ? route.params.code : undefined);

watch([market, activeTab, signalCode], async ([currentMarket, tab, code], _, onCleanup) => {
  let stale = false;
  onCleanup(() => { stale = true; });
  availableDates.value = [];
  datesError.value = null;
  datesLoading.value = false;
  if (tab === 'datasets' || tab === 'models') return;
  datesLoading.value = true;
  try {
    const result = await quantApi.dates(currentMarket, tab, tab === 'signals' ? code : undefined);
    if (!stale) availableDates.value = result.items;
  } catch (error) {
    if (!stale) datesError.value = getParsedApiError(error);
  } finally {
    if (!stale) datesLoading.value = false;
  }
}, { immediate: true });

function selectTradeDate(value: string) {
  if (!value || availableDates.value.includes(value)) void setTradeDate(value);
}
</script>

<template>
  <div class="min-w-0 space-y-4">
    <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
      <ModuleTabs
        :items="navItems"
        :active-key="activeTab"
        label="量化研究导航"
      />
      <div class="flex shrink-0 items-end gap-3">
        <p
          class="flex h-10 items-center text-xs text-muted-foreground"
          data-testid="quant-scope-description"
        >
          {{ scopeDescription }}
        </p>
        <div
          v-if="activeTab !== 'datasets' && activeTab !== 'models'"
          class="w-56"
        >
          <AppDatePicker
            label="交易日"
            :model-value="tradeDate"
            :available-dates="availableDates"
            :disabled="datesLoading || !availableDates.length"
            placeholder="最新数据"
            data-testid="quant-trade-date"
            class="w-full"
            @update:model-value="selectTradeDate"
          />
        </div>
        <ResearchMarketToggle
          :model-value="market"
          data-testid="quant-market-switcher"
          @update:model-value="setMarket"
        />
      </div>
    </div>
    <AppApiErrorAlert
      v-if="datesError"
      :error="datesError"
    />
    <section class="min-w-0">
      <RouterView />
    </section>
  </div>
</template>
