<script setup lang="ts">
import Badge from '@/components/common/Badge.vue';
import { cn } from '@/utils/cn';
import type { StockSuggestion } from '@/types/stockIndex';

const MARKET_BADGE_CONFIG = {
  CN: { label: 'A股', className: 'border-danger/25 bg-danger/10 text-danger' },
  HK: { label: '港股', className: 'border-success/25 bg-success/10 text-success' },
  US: { label: '美股', className: 'border-cyan/25 bg-cyan/10 text-cyan' },
  INDEX: { label: '指数', className: 'border-purple/25 bg-purple/10 text-purple' },
  ETF: { label: 'ETF', className: 'border-warning/25 bg-warning/10 text-warning' },
  BSE: { label: '北交所', className: 'border-orange-500/25 bg-orange-500/10 text-orange-500' },
} as const;

function marketBadgeClass(market: string) {
  const config = MARKET_BADGE_CONFIG[market as keyof typeof MARKET_BADGE_CONFIG];
  if (!config) {
    throw new Error(`Unsupported market in stock suggestion: ${market}`);
  }
  return cn('min-w-[3rem] justify-center shadow-none', config.className);
}

function marketLabel(market: string) {
  const config = MARKET_BADGE_CONFIG[market as keyof typeof MARKET_BADGE_CONFIG];
  if (!config) {
    throw new Error(`Unsupported market in stock suggestion: ${market}`);
  }
  return config.label;
}

function matchTypeClass(matchType: string) {
  const configMap = {
    exact: 'border-cyan/25 bg-cyan/10 text-cyan',
    prefix: 'border-purple/25 bg-purple/10 text-purple',
    contains: 'border-warning/25 bg-warning/10 text-warning',
    fuzzy: 'border-border/55 bg-elevated/75 text-muted-text',
  };
  return cn('shrink-0 shadow-none', configMap[matchType as keyof typeof configMap] || configMap.fuzzy);
}

function matchTypeLabel(matchType: string) {
  const configMap = {
    exact: '精确',
    prefix: '前缀',
    contains: '包含',
    fuzzy: '模糊',
  };
  return configMap[matchType as keyof typeof configMap] || configMap.fuzzy;
}

const props = defineProps<{
  suggestions: StockSuggestion[];
  highlightedIndex: number;
  listStyle?: Record<string, string | number | undefined>;
}>();

const emit = defineEmits<{
  select: [suggestion: StockSuggestion];
  mouseEnter: [index: number];
}>();
</script>

<template>
  <ul
    v-if="props.suggestions.length > 0"
    id="suggestions-list"
    class="z-[100] max-h-60 overflow-auto rounded-b-lg rounded-t-none border-x border-b"
    :style="{
      position: 'fixed',
      ...props.listStyle,
      backgroundColor: 'hsl(var(--card) / 0.85)',
      borderColor: 'var(--border-accent)',
      boxShadow:
        '0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3), -4px 0 15px -3px rgba(0, 0, 0, 0.2), 4px 0 15px -3px rgba(0, 0, 0, 0.2)',
    }"
    role="listbox"
  >
    <li
      v-for="(suggestion, index) in props.suggestions"
      :key="suggestion.canonicalCode"
      role="option"
      :aria-selected="index === highlightedIndex"
      :class="
        cn(
          'flex cursor-pointer items-center justify-between px-4 py-1',
          'hover:bg-[var(--autocomplete-hover-bg)]/25',
          index === highlightedIndex && 'bg-[var(--autocomplete-hover-bg)]/25',
        )
      "
      @mousedown.prevent
      @click="emit('select', suggestion)"
      @mouseenter="emit('mouseEnter', index)"
    >
      <div class="flex items-center gap-3">
        <Badge variant="default" size="sm" :class="marketBadgeClass(suggestion.market)">
          {{ marketLabel(suggestion.market) }}
        </Badge>
        <div class="flex flex-col">
          <span class="text-sm font-medium text-primary-text">
            {{ suggestion.nameZh }}
          </span>
          <span class="text-sm text-secondary-text">
            {{ suggestion.displayCode }}
          </span>
        </div>
      </div>
      <Badge variant="default" size="sm" :class="matchTypeClass(suggestion.matchType)">
        {{ matchTypeLabel(suggestion.matchType) }}
      </Badge>
    </li>
  </ul>
</template>
