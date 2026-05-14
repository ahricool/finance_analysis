export interface StockAutocompleteProps {
  value: string;
  onChange?: (value: string) => void;
  onSubmit?: (code: string, name?: string, source?: 'manual' | 'autocomplete') => void;
  disabled?: boolean;
  placeholder?: string;
  class?: string;
}

export interface SuggestionsListProps {
  suggestions: import('@/types/stockIndex').StockSuggestion[];
  highlightedIndex: number;
  onSelect: (suggestion: import('@/types/stockIndex').StockSuggestion) => void;
  onMouseEnter: (index: number) => void;
  style?: Record<string, string>;
}

export { default as StockAutocomplete } from './StockAutocomplete.vue';
export { default as SuggestionsList } from './SuggestionsList.vue';
