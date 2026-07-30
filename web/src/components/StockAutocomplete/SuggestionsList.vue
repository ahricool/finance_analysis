<script setup lang="ts">
import { Badge } from '@/components/ui/badge';
import { cn } from '@/utils/cn';
import type { StockSuggestion } from '@/types/stockIndex';

const MARKET_BADGE_CONFIG = {
  CN: { label: 'A股', className: 'border-destructive/25 bg-destructive/10 text-destructive' },
  HK: { label: '港股', className: 'border-success/25 bg-success/10 text-success' },
  US: { label: '美股', className: 'border-primary/25 bg-primary/10 text-primary' },
  INDEX: { label: '指数', className: 'border-border bg-muted text-muted-foreground' },
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
    exact: 'border-primary/25 bg-primary/10 text-primary',
    prefix: 'border-primary/20 bg-primary/5 text-primary',
    contains: 'border-warning/25 bg-warning/10 text-warning',
    fuzzy: 'border-border/55 bg-card/75 text-muted-foreground',
  };
  return cn(
    'shrink-0 shadow-none',
    configMap[matchType as keyof typeof configMap] || configMap.fuzzy,
  );
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
    class="z-[200] max-h-60 overflow-auto rounded-b-lg rounded-t-none border-x border-b border-border bg-popover/95 shadow-xl backdrop-blur-sm"
    :style="{
      position: 'fixed',
      ...props.listStyle,
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
          'hover:bg-accent/60',
          index === highlightedIndex && 'bg-accent/60',
        )
      "
      @mousedown.prevent
      @click="emit('select', suggestion)"
      @mouseenter="emit('mouseEnter', index)"
    >
      <div class="flex items-center gap-3">
        <Badge
          variant="default"
          size="sm"
          :class="marketBadgeClass(suggestion.market)"
        >
          {{ marketLabel(suggestion.market) }}
        </Badge>
        <div class="flex flex-col">
          <span class="text-sm font-medium text-foreground">
            {{ suggestion.nameZh }}
          </span>
          <span class="text-sm text-muted-foreground">
            {{ suggestion.displayCode }}
          </span>
        </div>
      </div>
      <Badge
        variant="default"
        size="sm"
        :class="matchTypeClass(suggestion.matchType)"
      >
        {{ matchTypeLabel(suggestion.matchType) }}
      </Badge>
    </li>
  </ul>
</template>
