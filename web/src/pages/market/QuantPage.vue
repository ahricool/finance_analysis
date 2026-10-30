<script setup lang="ts">
import { Button } from '@/components/ui/button';
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import ResearchMarketToggle from '@/components/research/ResearchMarketToggle.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import ModuleTabs from '@/components/layout/ModuleTabs.vue';
import { useQuantMarket } from '@/composables/useQuantMarket';
import { BarChart3, Bot, BriefcaseBusiness, LayoutDashboard } from 'lucide-vue-next';
import { computed, ref, watch } from 'vue';
import { useAuthStore } from '@/stores/authStore';
import type { QuantStatus } from '@/types/quant';
import { RouterView, useRoute } from 'vue-router';

type QuantTab = 'dashboard' | 'signals' | 'datasets' | 'models' | 'portfolios';

const route = useRoute();
const { market, setMarket, marketQuery, tradeDate, setTradeDate } = useQuantMarket();
const auth = useAuthStore();
const status = ref<QuantStatus | null>(null);
const statusFailed = ref(false);
watch(market, async (current, _, onCleanup) => {
  let stale = false; onCleanup(() => { stale = true; }); status.value = null; statusFailed.value=false;
  try { const value = await quantApi.status(current); if (!stale) status.value = value; } catch { if(!stale) statusFailed.value=true; }
}, { immediate: true });
const scopeDescription = computed(() => status.value ? `当前范围：${status.value.universeName} · ${status.value.memberCount}只` : statusFailed.value ? '研究范围读取失败，请刷新重试' : '正在读取研究范围');
const baseNavItems = [
  { key: 'dashboard' as const, label: '总览', icon: LayoutDashboard, path: '/research/quant' },
  { key: 'signals' as const, label: '个股排名', icon: BarChart3, path: '/research/quant/signals' },
  { key: 'models' as const, label: '模型管理', icon: Bot, path: '/research/quant/models' },
  {
    key: 'portfolios' as const,
    label: '目标组合',
    icon: BriefcaseBusiness,
    path: '/research/quant/portfolios',
  },
];
const navItems = computed(() =>
  baseNavItems.filter(item => item.key !== 'models' || auth.currentUser?.role === 'admin').map((item) => ({
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
  <div class="quant-workspace min-w-0 space-y-6">
    <PageHeader
      variant="section"
      title="量化研究"
    />
    <div class="flex min-w-0 flex-col gap-3">
      <ModuleTabs
        :items="navItems"
        :active-key="activeTab"
        label="量化研究导航"
      />
      <div class="research-toolbar flex min-w-0 flex-wrap items-end gap-3 rounded-xl border border-border/60 bg-muted/20 p-3">
        <ResearchMarketToggle
          :model-value="market"
          data-testid="quant-market-switcher"
          @update:model-value="setMarket"
        />
        <p
          class="flex h-10 max-w-full items-center text-xs text-muted-foreground"
          data-testid="quant-scope-description"
        >
          {{ scopeDescription }}
        </p>
        <div
          v-if="activeTab !== 'datasets' && activeTab !== 'models'"
          class="w-full max-w-56 sm:w-56"
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
          <Button
            v-if="tradeDate"
            variant="ghost"
            size="sm"
            @click="setTradeDate('')"
          >
            返回最新结果
          </Button>
        </div>
      </div>
    </div>
    <AppApiErrorAlert
      v-if="datesError"
      :error="datesError"
    />
    <p
      v-if="status?.latestAttempt?.error"
      class="text-sm text-destructive"
      role="status"
    >
      {{ status.latestAttempt.tradeDate }}：{{ status.latestAttempt.error }}；下方保留最后成功结果。
    </p>
    <section class="min-w-0">
      <RouterView />
    </section>
  </div>
</template>

<style scoped>
.quant-workspace :deep([data-slot="card"]) { box-shadow: none; border: 1px solid hsl(var(--border)); --tw-ring-shadow: 0 0 #0000; }
.quant-workspace :deep([data-slot="card-title"]) { letter-spacing: -.02em; font-weight: 600; }
.quant-workspace :deep([data-slot="table-container"]) { max-height: 70vh; border-radius: .65rem; border: 1px solid hsl(var(--border)); }
.quant-workspace :deep(thead) { position: sticky; top: 0; z-index: 2; background: hsl(var(--card)); }
.quant-workspace :deep(th) { background: color-mix(in srgb, hsl(var(--muted)) 55%, hsl(var(--card))); font-size: .75rem; }
.quant-workspace :deep(td) { padding: .9rem 1rem; font-variant-numeric: tabular-nums; white-space: nowrap; }
.quant-workspace :deep(tbody tr) { transition: background-color .15s; }
.quant-workspace :deep(tbody tr:hover) { background: color-mix(in srgb, hsl(var(--muted)) 45%, transparent); }
.quant-workspace :deep(.quant-filters) { display: flex; flex-wrap: wrap; align-items: end; gap: 1rem; padding-top: 0; }
.quant-workspace :deep(.quant-filters > :first-child) { flex: 1; min-width: 12rem; }
.quant-workspace :deep(.quant-signal-buy) { color: hsl(var(--primary)); background: color-mix(in srgb, hsl(var(--primary)) 8%, transparent); border-color: color-mix(in srgb, hsl(var(--primary)) 25%, transparent); }
.quant-workspace :deep(.quant-signal-avoid) { color: hsl(var(--muted-foreground)); }
.quant-workspace :deep(section.grid [data-slot="card"]) { background: linear-gradient(145deg, hsl(var(--card)), color-mix(in srgb, hsl(var(--muted)) 35%, hsl(var(--card)))); }
.quant-workspace :deep(section.grid [data-slot="card-title"]) { font-variant-numeric: tabular-nums; letter-spacing: -.035em; }
</style>
