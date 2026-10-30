<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router';
import { useMarket } from '@/composables/useMarket';
import { useMarketStore } from '@/stores/marketStore';
import { Switch } from '@/components/ui/switch';
import { useStockDetail } from '@/composables/useStockDetail';

const route = useRoute();
const router = useRouter();
const store = useMarketStore();
const { market } = useMarket();
const disabled = computed(() => route.meta.marketScope !== 'selectable');
const displayedMarket = computed(() => route.meta.marketScope === 'CN' || route.meta.marketScope === 'US'
  ? route.meta.marketScope : market.value);
async function setChecked(checked: boolean) {
  if (disabled.value) return;
  const next = checked ? 'US' : 'CN';
  if (next === market.value) return;
  // Detail identifiers and dates belong to the previous market.
  const query: LocationQueryRaw = { ...route.query, market: next };
  for (const key of ['tradeDate', 'symbol']) delete query[key];
  let path = route.path;
  if (route.name === 'strategy-detail') path = '/strategies';
  if (route.name === 'research-quant-signal-detail') path = '/research/quant/signals';
  if (route.name === 'research-quant-model-run') path = '/research/quant/models';
  const failure = await router.push({ path, query, hash: route.hash });
  if (!failure) {
    store.setMarket(next);
    useStockDetail().close();
  }
}
</script>

<template>
  <div
    class="mr-2 flex shrink-0 items-center gap-1.5 text-xs font-medium"
    data-testid="global-market-control"
  >
    <span :class="!disabled && displayedMarket === 'CN' ? 'text-foreground' : 'text-muted-foreground'">A 股</span>
    <Switch
      :model-value="displayedMarket === 'US'"
      aria-label="切换 A 股／美股"
      :disabled="disabled"
      data-testid="global-market-switch"
      @update:model-value="setChecked"
    />
    <span :class="!disabled && displayedMarket === 'US' ? 'text-foreground' : 'text-muted-foreground'">美股</span>
  </div>
</template>
