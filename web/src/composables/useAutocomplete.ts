import { onUnmounted, ref, type Ref } from 'vue';
import type { StockIndexItem, StockSuggestion } from '@/types/stockIndex';
import { searchStocks } from '@/utils/searchStocks';
import { SEARCH_CONFIG } from '@/utils/stockIndexFields';

export interface UseAutocompleteOptions {
  minLength?: number;
  debounceMs?: number;
  limit?: number;
}

export interface UseAutocompleteResult {
  query: Ref<string>;
  setQuery: (value: string) => void;
  suggestions: Ref<StockSuggestion[]>;
  isOpen: Ref<boolean>;
  highlightedIndex: Ref<number>;
  setHighlightedIndex: (index: number) => void;
  highlightPrevious: () => void;
  highlightNext: () => void;
  handleSelect: (suggestion: StockSuggestion) => void;
  close: () => void;
  reset: () => void;
  isComposing: Ref<boolean>;
  setIsComposing: (composing: boolean) => void;
  runtimeFallback: Ref<boolean>;
  error: Ref<Error | null>;
}

export function useAutocomplete(
  getIndex: () => StockIndexItem[],
  options: UseAutocompleteOptions = {},
): UseAutocompleteResult {
  const {
    minLength = SEARCH_CONFIG.MIN_QUERY_LENGTH,
    debounceMs = SEARCH_CONFIG.DEBOUNCE_MS,
    limit = SEARCH_CONFIG.DEFAULT_LIMIT,
  } = options;

  const query = ref('');
  const suggestions = ref<StockSuggestion[]>([]);
  const isOpen = ref(false);
  const highlightedIndex = ref(-1);
  const isComposing = ref(false);
  const runtimeFallback = ref(false);
  const error = ref<Error | null>(null);
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function runSearch(q: string) {
    if (runtimeFallback.value) {
      return;
    }

    if (q.length < minLength) {
      suggestions.value = [];
      isOpen.value = false;
      highlightedIndex.value = -1;
      return;
    }

    try {
      const results = searchStocks(q, getIndex(), { limit });
      suggestions.value = results;
      isOpen.value = results.length > 0;
      highlightedIndex.value = -1;
    } catch (caught) {
      const runtimeError = caught instanceof Error ? caught : new Error('Autocomplete search failed');
      console.error('Autocomplete search failed. Falling back to plain input.', runtimeError);
      error.value = runtimeError;
      runtimeFallback.value = true;
      suggestions.value = [];
      isOpen.value = false;
      highlightedIndex.value = -1;
    }
  }

  function setQuery(value: string) {
    query.value = value;

    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }

    if (runtimeFallback.value) {
      return;
    }

    debounceTimer = setTimeout(() => {
      runSearch(value);
    }, debounceMs);
  }

  function handleSelect(suggestion: StockSuggestion) {
    query.value = suggestion.displayCode;
    isOpen.value = false;
    suggestions.value = [];
    highlightedIndex.value = -1;
  }

  function highlightPrevious() {
    highlightedIndex.value =
      highlightedIndex.value <= 0 ? suggestions.value.length - 1 : highlightedIndex.value - 1;
  }

  function highlightNext() {
    highlightedIndex.value =
      highlightedIndex.value >= suggestions.value.length - 1 ? 0 : highlightedIndex.value + 1;
  }

  function close() {
    isOpen.value = false;
    highlightedIndex.value = -1;
  }

  function reset() {
    query.value = '';
    suggestions.value = [];
    isOpen.value = false;
    highlightedIndex.value = -1;
  }

  onUnmounted(() => {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
  });

  return {
    query,
    setQuery,
    suggestions,
    isOpen,
    highlightedIndex,
    setHighlightedIndex: (i: number) => {
      highlightedIndex.value = i;
    },
    highlightPrevious,
    highlightNext,
    handleSelect,
    close,
    reset,
    isComposing,
    setIsComposing: (v: boolean) => {
      isComposing.value = v;
    },
    runtimeFallback,
    error,
  };
}
