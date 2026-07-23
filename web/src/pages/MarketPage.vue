<script setup lang="ts">
import { Activity, Star, Wallet } from 'lucide-vue-next';
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import SectionNavItems from '@/components/common/SectionNavItems.vue';
import SectionNavPanel from '@/components/common/SectionNavPanel.vue';
import SectionPageHeader from '@/components/common/SectionPageHeader.vue';

type MarketTab = 'watch-list' | 'holdings' | 'signals';

const route = useRoute();
const navItems = [
  { key: 'watch-list' as const, label: '自选股', icon: Star, to: '/market/watch-list' },
  { key: 'holdings' as const, label: '持仓股', icon: Wallet, to: '/market/holdings' },
  { key: 'signals' as const, label: '信号评估', icon: Activity, to: '/market/signals' },
];

const activeTab = computed<MarketTab>(() => {
  if (route.path.endsWith('/holdings')) return 'holdings';
  if (route.path.endsWith('/signals')) return 'signals';
  return 'watch-list';
});

</script>

<template>
  <div class="space-y-5">
    <SectionPageHeader
      title="市场"
      description="管理自选股、持仓股并查看历史信号。"
    />

    <nav
      class="grid grid-cols-3 gap-1 rounded-2xl border border-border/70 bg-card/94 p-2 shadow-soft-card backdrop-blur-sm lg:hidden"
      aria-label="市场页面导航"
      data-testid="market-mobile-nav"
    >
      <SectionNavItems :items="navItems" :active-key="activeTab" responsive />
    </nav>

    <div class="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
      <SectionNavPanel
        class="hidden lg:block"
        data-testid="market-desktop-nav"
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
