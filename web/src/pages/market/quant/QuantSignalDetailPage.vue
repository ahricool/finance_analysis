<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuantMarket } from '@/composables/useQuantMarket';
import StockDetailDialog from '@/components/stocks/StockDetailDialog.vue';
const route = useRoute();
const router = useRouter();
const { market, marketQuery, tradeDate } = useQuantMarket();
const stock = computed(() => ({ code: String(route.params.code || ''), name: '', market_type: market.value }));
function close(open: boolean) {
  if (open) return;
  // Direct and external entry must never send the user out of the app.
  void router.replace({ path: '/research/quant/signals', query: marketQuery() });
}
</script>
<template>
  <div class="space-y-4">
    <RouterLink
      :to="{ path: '/research/quant/signals', query: marketQuery() }"
      class="text-sm underline underline-offset-4"
    >
      ← 返回排名
    </RouterLink>
    <StockDetailDialog
      :open="true"
      :stock="stock"
      kind="research"
      initial-tab="quant"
      :context="{ tradeDate: tradeDate || undefined, view: 'official' }"
      @update:open="close"
    />
  </div>
</template>
