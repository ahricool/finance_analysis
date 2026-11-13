<script setup lang="ts">
import { computed } from 'vue';
import { RouterView, useRoute } from 'vue-router';
import ModuleLayout from '@/components/layout/ModuleLayout.vue';
import { marketNavItems } from '@/config/mainNav';

type MarketTab = 'prediction-events' | 'watch-list' | 'holdings' | 'holdings-review' | 'heatmap' | 'intraday-options';

const route = useRoute();

const activeTab = computed<MarketTab>(() => {
  if (route.path.endsWith('/prediction-events')) return 'prediction-events';
  if (route.path.endsWith('/holdings-review')) return 'holdings-review';
  if (route.path.endsWith('/intraday-options')) return 'intraday-options';
  if (route.path.endsWith('/heatmap')) return 'heatmap';
  if (route.path.endsWith('/holdings')) return 'holdings';
  return 'watch-list';
});
</script>

<template>
  <div class="page-shell">
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
