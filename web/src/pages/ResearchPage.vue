<script setup lang="ts">
import { RefreshCcw, Sigma, TrendingUp } from 'lucide-vue-next';
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import ModuleTabs from '@/components/layout/ModuleTabs.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Separator } from '@/components/ui/separator';

type ResearchTab = 'quant' | 'etf-rotation' | 'trend-following';

const route = useRoute();
const navItems = [
  { key: 'quant' as const, label: '量化研究', icon: Sigma, to: '/market/quant' },
  { key: 'etf-rotation' as const, label: 'ETF动量轮动', icon: RefreshCcw, to: '/market/etf-rotation' },
  { key: 'trend-following' as const, label: '趋势跟踪', icon: TrendingUp, to: '/market/trend-following' },
];

const activeTab = computed<ResearchTab>(() =>
  route.path.startsWith('/market/etf-rotation')
    ? 'etf-rotation'
    : route.path.startsWith('/market/trend-following') ? 'trend-following' : 'quant',
);
</script>

<template>
  <div class="space-y-6 py-4 sm:py-6">
    <PageHeader
      title="研究"
      description="研究量化模型、ETF 动量轮动与独立趋势跟踪策略。"
    />
    <ModuleTabs
      :items="navItems"
      :active-key="activeTab"
      label="研究页面导航"
    />
    <Separator />
    <section class="min-w-0">
      <RouterView />
    </section>
  </div>
</template>
