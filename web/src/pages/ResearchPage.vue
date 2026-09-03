<script setup lang="ts">
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import ModuleTabs from '@/components/layout/ModuleTabs.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Separator } from '@/components/ui/separator';
import { researchNavItems } from '@/config/mainNav';

type ResearchTab = 'quant' | 'etf-rotation' | 'trend-following';

const route = useRoute();

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
      :items="researchNavItems"
      :active-key="activeTab"
      label="研究页面导航"
    />
    <Separator />
    <section class="min-w-0">
      <RouterView />
    </section>
  </div>
</template>
