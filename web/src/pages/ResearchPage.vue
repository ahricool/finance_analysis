<script setup lang="ts">
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import ModuleTabs from '@/components/layout/ModuleTabs.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Separator } from '@/components/ui/separator';
import { researchNavItems } from '@/config/mainNav';

type ResearchTab = 'quant' | 'etf-rotation' | 'trend-following' | 'crypto-btc';

const route = useRoute();

const activeTab = computed<ResearchTab>(() => {
  if (route.path.startsWith('/research/crypto/btc')) return 'crypto-btc';
  if (route.path.startsWith('/research/etf-rotation')) return 'etf-rotation';
  if (route.path.startsWith('/research/trend-following')) return 'trend-following';
  return 'quant';
});
</script>

<template>
  <div class="space-y-6 py-4 sm:py-6">
    <PageHeader
      title="研究"
      description="研究量化模型、ETF 动量轮动、趋势跟踪与 BTC 策略。"
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
