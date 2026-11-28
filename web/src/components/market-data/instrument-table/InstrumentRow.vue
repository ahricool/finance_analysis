<script setup lang="ts">
import { computed, defineAsyncComponent, inject, provide, ref, watch } from 'vue';
import { cn } from '@/utils/cn';
import { expansionKey, rowVisibleKey, tableChartPeriod, virtualChartHeight } from './state';
import { useNearViewport } from './useNearViewport';
import LazyChartPanel from './LazyChartPanel.vue';

const StockDailyChart = defineAsyncComponent(() => import('./StockDailyChart.vue'));
const IntradayStockPanel = defineAsyncComponent(() => import('@/components/stocks/IntradayStockPanel.vue'));
defineOptions({ inheritAttrs: false });
const props = defineProps<{
  symbol?: string | null; rowId?: string | number; market?: string; virtual?: boolean; allPeriods?: boolean; noCandles?: boolean;
}>();
const table = inject(expansionKey)!;
const row = ref<HTMLTableRowElement | null>(null);
const visible = useNearViewport(row);
provide(rowVisibleKey, visible);
const emit = defineEmits<{ visibility: [code: string, visible: boolean] }>();
watch([() => props.symbol, visible], ([code, near], _, cleanup) => {
  if (!code || !near) return;
  emit('visibility', code, true);
  cleanup(() => emit('visibility', code, false));
});
const id = computed(() => props.rowId ?? props.symbol ?? '');
const expanded = computed(() => !!props.symbol && table.expanded(id.value));
const market = computed(() => props.market ?? (/\.(SH|SZ|BJ)$/i.test(props.symbol ?? '') ? 'CN' : /\.HK$/i.test(props.symbol ?? '') ? 'HK' : 'US'));
function toggle(event: MouseEvent | KeyboardEvent) {
  if (!props.symbol) return;
  if (event.target instanceof Element && event.target.closest('button,a,input,select,textarea,summary,[role="button"]')) return;
  table.toggle(id.value);
}
</script>

<template>
  <tr
    ref="row"
    data-slot="table-row"
    v-bind="$attrs"
    :class="cn('border-b transition-colors hover:bg-muted/50', symbol && 'cursor-pointer focus-visible:bg-muted/70', $attrs.class as string)"
    :tabindex="symbol ? 0 : undefined"
    :aria-expanded="symbol ? expanded : undefined"
    :aria-label="symbol ? symbol + ' K 线' : undefined"
    @click="toggle"
    @keydown.enter.self.prevent="toggle"
    @keydown.space.self.prevent="toggle"
  >
    <slot :expanded="expanded" />
  </tr>
  <tr
    v-if="expanded && symbol"
    data-testid="instrument-chart-row"
  >
    <td
      :colspan="row?.cells.length || 1"
      class="max-w-0 p-0"
    >
      <div :style="virtual ? { height: virtualChartHeight + 'px', overflow: 'auto' } : undefined">
        <LazyChartPanel
          v-if="!noCandles && (allPeriods || tableChartPeriod === '1d' || tableChartPeriod === '1m')"
          :row-visible="visible"
        >
          <slot
            name="chart"
            :period="tableChartPeriod"
          >
            <StockDailyChart
              v-if="tableChartPeriod === '1d'"
              :symbol="symbol"
            />
            <IntradayStockPanel
              v-else-if="market === 'CN' || market === 'HK' || market === 'US'"
              :symbol="symbol"
              :market="market"
            />
            <p
              v-else
              class="p-6 text-sm text-muted-foreground"
            >
              无数据
            </p>
          </slot>
        </LazyChartPanel>
        <p
          v-else
          class="px-4 py-6 text-sm text-muted-foreground"
        >
          无数据
        </p>
      </div>
    </td>
  </tr>
</template>
