import { computed, ref, onMounted } from 'vue';
import type { StockIndexItem } from '@/types/stockIndex';
import { loadStockIndex } from '@/utils/stockIndexLoader';

export interface UseStockIndexResult {
  index: ReturnType<typeof ref<StockIndexItem[]>>;
  loading: ReturnType<typeof ref<boolean>>;
  error: ReturnType<typeof ref<Error | null>>;
  fallback: ReturnType<typeof ref<boolean>>;
  loaded: ReturnType<typeof computed<boolean>>;
}

export function useStockIndex() {
  const index = ref<StockIndexItem[]>([]);
  const loading = ref(true);
  const error = ref<Error | null>(null);
  const fallback = ref(false);

  onMounted(async () => {
    loading.value = true;
    error.value = null;
    const result = await loadStockIndex();
    index.value = result.data;
    fallback.value = result.fallback;
    if (result.error) {
      error.value = result.error;
    }
    loading.value = false;
  });

  const loaded = computed(() => !loading.value);

  return {
    index,
    loading,
    error,
    fallback,
    loaded,
  };
}
