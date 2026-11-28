<script setup lang="ts">
import { anchorMarket } from './anchorMarket';
import { computed } from 'vue';
import type { Contract } from '@/api/contracts';
import { useStockDetail } from '@/composables/useStockDetail';
import { useSecurityName } from '@/composables/useSecurityName';

const props = defineProps<{ symbol: string; contract?: Contract; onOpenContract?: () => void }>();
const detail = useStockDetail();
const anchor = computed(() => props.contract?.underlying_symbol);
const market = computed(() => anchorMarket(anchor.value ?? ''));
const equityName = useSecurityName(() => ['US', 'HK', 'CN'].includes(market.value) ? anchor.value : null, null);
const label = computed(() => (equityName.value ?? anchor.value?.replace(/\.(CRYPTO|OTHER)$/, '') ?? props.symbol.replace(/USDT$/, '')) + ' 永续');
function open() {
  if (props.onOpenContract) return props.onOpenContract();
  detail.open({ code: anchor.value ?? props.symbol, name: equityName.value, marketType: market.value });
}
</script>

<template>
  <button
    type="button"
    class="text-left hover:underline"
    :aria-label="symbol + ' 标的详情'"
    @click.stop="open"
  >
    <span class="font-mono text-xs text-muted-foreground">{{ symbol }} - </span><strong>{{ label }}</strong>
  </button>
</template>
