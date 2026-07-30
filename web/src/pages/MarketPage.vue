<script setup lang="ts">
import { Activity, Star, Wallet } from 'lucide-vue-next';
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import ModuleTabs from '@/components/layout/ModuleTabs.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Separator } from '@/components/ui/separator';

type MarketTab = 'watch-list' | 'holdings' | 'signals';

const route = useRoute();
const navItems = [
  { key: 'watch-list' as const, label: '自选股', icon: Star, to: '/market/watch-list' },
  { key: 'holdings' as const, label: '投资组合', icon: Wallet, to: '/market/holdings' },
  { key: 'signals' as const, label: '信号评估', icon: Activity, to: '/market/signals' },
];

const activeTab = computed<MarketTab>(() => {
  if (route.path.endsWith('/holdings')) return 'holdings';
  if (route.path.endsWith('/signals')) return 'signals';
  return 'watch-list';
});
</script>

<template>
  <div class="space-y-6 py-4 sm:py-6">
    <PageHeader
      title="市场"
      description="管理自选股、投资组合并查看历史信号。"
    />
    <ModuleTabs
      :items="navItems"
      :active-key="activeTab"
      label="市场页面导航"
    />
    <Separator />
    <section class="min-w-0">
      <RouterView />
    </section>
  </div>
</template>
