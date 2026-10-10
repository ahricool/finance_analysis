<script setup lang="ts">
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import ModuleLayout from '@/components/layout/ModuleLayout.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { researchNavItems } from '@/config/mainNav';

type ResearchTab = 'options-intelligence' | 'signal-center' | 'intraday-confirmation' | 'confluence' | 'dragon-tiger-flow' | 'market-sentiment' | 'industry-strength' | 'macro' | 'quant' | 'etf-rotation' | 'trend-following';

const route = useRoute();

const activeTab = computed<ResearchTab>(() => {
  if (route.path.startsWith('/research/options-intelligence')) return 'options-intelligence';
  if (route.path.startsWith('/research/signal-center')) return 'signal-center';
  if (route.path.startsWith('/research/intraday-confirmation')) return 'intraday-confirmation';
  if (route.path.startsWith('/research/confluence')) return 'confluence';
  if (route.path.startsWith('/research/dragon-tiger-flow')) return 'dragon-tiger-flow';
  if (route.path.startsWith('/research/market-sentiment')) return 'market-sentiment';
  if (route.path.startsWith('/research/industry-strength')) return 'industry-strength';
  if (route.path.startsWith('/research/macro')) return 'macro';
  if (route.path.startsWith('/research/etf-rotation')) return 'etf-rotation';
  if (route.path.startsWith('/research/trend-following')) return 'trend-following';
  return 'quant';
});
</script>

<template>
  <div class="page-shell">
    <PageHeader
      title="研究"
      en="Research"
      description="研究量化模型、ETF 动量轮动、趋势跟踪、行业强度、龙虎榜资金、市场情绪与宏观环境。"
    />
    <ModuleLayout
      :items="researchNavItems"
      :active-key="activeTab"
      label="研究页面导航"
    >
      <section class="min-w-0">
        <RouterView />
      </section>
    </ModuleLayout>
  </div>
</template>
