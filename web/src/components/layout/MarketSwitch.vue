<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router';
import { useMarket } from '@/composables/useMarket';
import { useMarketStore } from '@/stores/marketStore';
import { useStockDetail } from '@/composables/useStockDetail';

const route = useRoute();
const router = useRouter();
const store = useMarketStore();
const { market } = useMarket();
const disabled = computed(() => route.meta.marketScope !== 'selectable');
const displayedMarket = computed(() => route.meta.marketScope === 'CN' || route.meta.marketScope === 'US'
  ? route.meta.marketScope : market.value);
async function toggle() {
  if (disabled.value) return;
  const next = market.value === 'CN' ? 'US' : 'CN';
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
    class="mr-2 flex shrink-0 items-center gap-1.5 text-xs font-medium transition-opacity"
    :class="disabled && 'opacity-40'"
    data-testid="global-market-control"
  >
    <span :class="displayedMarket === 'CN' ? 'text-foreground' : 'text-muted-foreground'">A 股</span>
    <button
      type="button"
      role="switch"
      aria-label="切换 A 股／美股"
      :aria-checked="displayedMarket === 'US'"
      :disabled="disabled"
      class="relative inline-flex h-6 w-10 shrink-0 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed"
      :class="displayedMarket === 'US' ? 'bg-foreground' : 'bg-muted-foreground/30'"
      data-testid="global-market-switch"
      @click="toggle"
    >
      <span
        class="pointer-events-none block size-4 rounded-full bg-background shadow-sm transition-transform"
        :class="displayedMarket === 'US' ? 'translate-x-5' : 'translate-x-1'"
      />
    </button>
    <span :class="displayedMarket === 'US' ? 'text-foreground' : 'text-muted-foreground'">美股</span>
  </div>
</template>
