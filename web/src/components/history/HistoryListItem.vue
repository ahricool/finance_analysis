<script setup lang="ts">
import { Badge } from '@/components/ui/badge';
import { getSentimentColor, type HistoryItem } from '@/types/analysis';
import { formatDateTime } from '@/utils/format';
import { truncateStockName, isStockNameTruncated } from '@/utils/stockName';
import { formatSecurityLabel } from '@/utils/security';
import { computed } from 'vue';

const props = defineProps<{
  item: HistoryItem;
  isViewing: boolean;
}>();

const emit = defineEmits<{
  select: [];
}>();

function getOperationBadgeLabel(advice?: string) {
  const normalized = advice?.trim();
  if (!normalized) {
    return '情绪';
  }
  if (normalized.includes('减仓')) {
    return '减仓';
  }
  if (normalized.includes('卖')) {
    return '卖出';
  }
  if (normalized.includes('观望') || normalized.includes('等待')) {
    return '观望';
  }
  if (normalized.includes('买') || normalized.includes('布局')) {
    return '买入';
  }
  return normalized.split(/[，。；、\s]/)[0] || '建议';
}

const barColor = computed(() =>
  props.item.sentimentScore !== undefined ? getSentimentColor(props.item.sentimentScore) : null,
);

const stockName = computed(() => formatSecurityLabel(props.item.stockCode, props.item.stockName));
const isTruncated = computed(() => isStockNameTruncated(stockName.value));
</script>

<template>
  <button
    type="button"
    data-testid="analysis-history-item"
    class="group/item w-full rounded-md p-3 text-left transition-colors hover:bg-muted"
    :class="isViewing ? 'bg-muted' : ''"
    @click="emit('select')"
  >
    <div
      :class="`relative z-10 flex items-center gap-2.5${isTruncated ? ' group-hover/item:z-20' : ''}`"
    >
      <div
        v-if="barColor"
        class="h-8 w-1 flex-shrink-0 rounded-full"
        :style="{ backgroundColor: barColor }"
      />
      <div class="min-w-0 flex-1">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0 flex-1">
            <span class="truncate text-sm font-semibold tracking-tight text-foreground">
              <span class="group-hover/item:hidden">{{ truncateStockName(stockName) }}</span>
              <span class="hidden group-hover/item:inline">{{ stockName }}</span>
            </span>
          </div>
          <Badge
            v-if="barColor"
            variant="outline"
            size="sm"
            :class="isTruncated ? 'shrink-0 group-hover/item:opacity-80' : 'shrink-0'"
            :inline-style="{
              color: barColor,
              borderColor: `${barColor}40`,
              backgroundColor: `${barColor}14`,
            }"
          >
            {{ getOperationBadgeLabel(item.operationAdvice) }} {{ item.sentimentScore }}
          </Badge>
        </div>
        <div class="mt-1 flex items-center gap-2">
          <span class="text-xs text-muted-foreground">
            {{ formatDateTime(item.createdAt) }}
          </span>
        </div>
      </div>
    </div>
  </button>
</template>
