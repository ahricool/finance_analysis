<script setup lang="ts">
import { FlaskConical, Sigma } from 'lucide-vue-next';
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import ModuleTabs from '@/components/layout/ModuleTabs.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Separator } from '@/components/ui/separator';

type ResearchTab = 'backtests' | 'quant';

const route = useRoute();
const navItems = [
  { key: 'backtests' as const, label: '策略回测', icon: FlaskConical, to: '/market/backtests' },
  { key: 'quant' as const, label: '量化研究', icon: Sigma, to: '/market/quant' },
];

const activeTab = computed<ResearchTab>(() =>
  route.path.startsWith('/market/quant') ? 'quant' : 'backtests',
);
</script>

<template>
  <div class="space-y-6 py-4 sm:py-6">
    <PageHeader
      title="研究"
      description="运行策略回测，管理量化数据集、模型与选股信号。"
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
