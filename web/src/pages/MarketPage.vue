<script setup lang="ts">
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import ModuleLayout from '@/components/layout/ModuleLayout.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { marketNavItems } from '@/config/mainNav';

type MarketTab = 'watch-list' | 'holdings';

const route = useRoute();

const activeTab = computed<MarketTab>(() => {
  if (route.path.endsWith('/holdings')) return 'holdings';
  return 'watch-list';
});
</script>

<template>
  <div class="page-shell">
    <PageHeader
      title="市场"
      en="Market"
      description="管理自选股，并维护数据库中的实际持仓。"
    />
    <ModuleLayout
      :items="marketNavItems"
      :active-key="activeTab"
      label="市场页面导航"
    >
      <section class="min-w-0">
        <RouterView />
      </section>
    </ModuleLayout>
  </div>
</template>
