import { shallowRef } from 'vue';
import type { StockDetailRecord } from '@/components/stocks/StockDetailDialog.vue';
import type { StockDetailContext } from '@/components/stocks/detail/types';

const selection = shallowRef<{ stock: StockDetailRecord; context?: StockDetailContext } | null>(null);
export function useStockDetail() {
  return {
    selection,
    open: (stock: StockDetailRecord, context?: StockDetailContext) => { selection.value = { stock, context }; },
    close: () => { selection.value = null; },
  };
}
