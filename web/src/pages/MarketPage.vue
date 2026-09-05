<script setup lang="ts">
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import ModuleTabs from '@/components/layout/ModuleTabs.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Separator } from '@/components/ui/separator';
import { marketNavItems } from '@/config/mainNav';

type MarketTab = 'watch-list' | 'holdings';

const route = useRoute();

const activeTab = computed<MarketTab>(() => {
  if (route.path.endsWith('/holdings')) return 'holdings';
  return 'watch-list';
});
</script>

<template>
  <div class="space-y-6 py-4 sm:py-6">
    <PageHeader
      title="市场"
      description="管理自选股和投资组合。"
    />
    <ModuleTabs
      :items="marketNavItems"
      :active-key="activeTab"
      label="市场页面导航"
    />
    <Separator />
    <section class="min-w-0">
      <RouterView />
    </section>
  </div>
</template>
