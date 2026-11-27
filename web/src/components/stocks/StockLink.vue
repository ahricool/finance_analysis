<script setup lang="ts">
import { computed } from 'vue';
import type { MarketType } from '@/api/watchList';
import type { StockDetailContext } from './detail/types';
import { useSecurityName } from '@/composables/useSecurityName';
import { useStockDetail } from '@/composables/useStockDetail';
import { formatSecurityLabel } from '@/utils/security';
import StockIdentity from './StockIdentity.vue';
defineOptions({ inheritAttrs: false });
const props = defineProps<{
  code: string;
  name?: string | null;
  market?: string | null;
  context?: StockDetailContext;
  researchLabel?: string;
  onSelect?: () => void;
}>();
const emit = defineEmits<{ research: [] }>();
const detail = useStockDetail();
const resolvedName = useSecurityName(() => props.code, () => props.name);
const market = computed<MarketType>(() => {
  if (props.market === 'CN' || props.market === 'US' || props.market === 'HK') return props.market;
  return /\.(SH|SZ|BJ)$/i.test(props.code) ? 'CN' : /\.HK$/i.test(props.code) ? 'HK' : 'US';
});
function open() {
  if (props.onSelect) props.onSelect();
  else detail.open({ code: props.code, name: resolvedName.value, marketType: market.value }, props.context);
}
</script>

<template>
  <button
    v-bind="$attrs"
    type="button"
    class="max-w-full rounded-sm text-left hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    :aria-label="formatSecurityLabel(code, resolvedName)"
    @click.stop.prevent="open"
    @keydown.enter.stop
    @keydown.space.stop
  >
    <StockIdentity
      :code="code"
      :name="resolvedName"
    />
  </button>
  <button
    v-if="researchLabel"
    type="button"
    class="block text-xs text-muted-foreground hover:underline"
    data-testid="row-research"
    @click.stop="emit('research')"
  >
    {{ researchLabel }}
  </button>
</template>
