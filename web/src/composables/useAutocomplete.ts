import axios from 'axios';
import { onUnmounted, ref, type Ref } from 'vue';
import { stocksApi, type InstrumentSearchItem } from '@/api/stocks';
import type { AssetType, Market, StockSuggestion } from '@/types/stockIndex';
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
  searching: Ref<boolean>;
  highlightedIndex: Ref<number>;
  setHighlightedIndex: (index: number) => void;
  highlightPrevious: () => void;
  highlightNext: () => void;
  handleSelect: (suggestion: StockSuggestion) => void;
  close: () => void;
  reset: () => void;
  isComposing: Ref<boolean>;
  setIsComposing: (composing: boolean) => void;
  error: Ref<Error | null>;
}

function isInstrumentMarket(value: string): value is Market {
  return value === 'CN' || value === 'HK' || value === 'US';
}

function instrumentTypeToAssetType(value: string): AssetType {
  const normalized = value.toUpperCase();
  if (normalized === 'ETF') return 'etf';
  if (normalized === 'INDEX') return 'index';
  return 'stock';
}

function toMatchType(value: string): StockSuggestion['matchType'] {
  if (value === 'exact' || value === 'prefix' || value === 'fuzzy') return value;
  return 'fuzzy';
}

export function toStockSuggestion(item: InstrumentSearchItem): StockSuggestion {
  const matchType = toMatchType(item.matchType);
  return {
    canonicalCode: item.code,
    displayCode: item.nativeCode || item.code,
    nameZh: item.name,
    market: isInstrumentMarket(item.market) ? item.market : 'CN',
    assetType: instrumentTypeToAssetType(item.instrumentType),
    matchType,
    matchField: matchType === 'fuzzy' ? 'name' : 'code',
    score: matchType === 'exact' ? 100 : matchType === 'prefix' ? 80 : 50,
  };
}

function isAbortError(error: unknown): boolean {
  return axios.isCancel(error) || (axios.isAxiosError(error) && error.code === 'ERR_CANCELED');
}

export function useAutocomplete(options: UseAutocompleteOptions = {}): UseAutocompleteResult {
  const {
    minLength = SEARCH_CONFIG.MIN_QUERY_LENGTH,
    debounceMs = SEARCH_CONFIG.DEBOUNCE_MS,
    limit = SEARCH_CONFIG.DEFAULT_LIMIT,
  } = options;

  const query = ref('');
  const suggestions = ref<StockSuggestion[]>([]);
  const isOpen = ref(false);
  const searching = ref(false);
  const highlightedIndex = ref(-1);
  const isComposing = ref(false);
  const error = ref<Error | null>(null);
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  let abortController: AbortController | null = null;
  let requestId = 0;

  function clearPending() {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    abortController?.abort();
    abortController = null;
  }

  async function runSearch(q: string) {
    const needle = q.trim();
    if (needle.length < minLength) {
      suggestions.value = [];
      isOpen.value = false;
      highlightedIndex.value = -1;
      searching.value = false;
      return;
    }

    abortController?.abort();
    const controller = new AbortController();
    abortController = controller;
    const id = ++requestId;
    searching.value = true;
    error.value = null;

    try {
      const results = await stocksApi.searchInstruments(needle, {
        limit,
        signal: controller.signal,
      });
      if (id !== requestId) return;
      suggestions.value = results.map(toStockSuggestion);
      isOpen.value = results.length > 0;
      highlightedIndex.value = -1;
    } catch (caught) {
      if (id !== requestId || isAbortError(caught)) return;
      error.value = caught instanceof Error ? caught : new Error('Autocomplete search failed');
      suggestions.value = [];
      isOpen.value = false;
      highlightedIndex.value = -1;
    } finally {
      if (id === requestId) {
        searching.value = false;
      }
    }
  }

  function setQuery(value: string) {
    query.value = value;
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      void runSearch(value);
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
    clearPending();
  });

  return {
    query,
    setQuery,
    suggestions,
    isOpen,
    searching,
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
    error,
  };
}
