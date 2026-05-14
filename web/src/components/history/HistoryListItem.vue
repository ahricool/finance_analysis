<script setup lang="ts">
import Badge from '@/components/common/Badge.vue';
import { getSentimentColor, type HistoryItem } from '@/types/analysis';
import { formatDateTime } from '@/utils/format';
import { truncateStockName, isStockNameTruncated } from '@/utils/stockName';
import { computed } from 'vue';

const props = defineProps<{
  item: HistoryItem;
  isViewing: boolean;
  isChecked: boolean;
  isDeleting: boolean;
}>();

const emit = defineEmits<{
  toggleChecked: [];
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

const stockName = computed(() => props.item.stockName || props.item.stockCode);
const isTruncated = computed(() => isStockNameTruncated(stockName.value));
</script>

<template>
  <div class="group flex items-start gap-2">
    <div class="pt-5">
      <input
        type="checkbox"
        :checked="isChecked"
        :disabled="isDeleting"
        class="h-3.5 w-3.5 cursor-pointer rounded border-subtle-hover bg-transparent accent-primary focus:ring-primary/30 disabled:opacity-50"
        @change="emit('toggleChecked')"
      />
    </div>
    <button
      type="button"
      class="home-history-item group/item flex-1 p-2.5 text-left"
      :class="isViewing ? 'home-history-item-selected' : ''"
      @click="emit('select')"
    >
      <div
        :class="`relative z-10 flex items-center gap-2.5${isTruncated ? ' group-hover/item:z-20' : ''}`"
      >
        <div
          v-if="barColor"
          class="h-8 w-1 flex-shrink-0 rounded-full"
          :style="{
            backgroundColor: barColor,
            boxShadow: `0 0 10px ${barColor}40`,
          }"
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
              variant="default"
              size="sm"
              :class="`home-history-sentiment-badge shrink-0 shadow-none text-[11px] font-semibold leading-none transition-opacity duration-200${isTruncated ? ' group-hover/item:opacity-80' : ''}`"
              :inline-style="{
                color: barColor,
                borderColor: `${barColor}30`,
                backgroundColor: `${barColor}10`,
              }"
            >
              {{ getOperationBadgeLabel(item.operationAdvice) }} {{ item.sentimentScore }}
            </Badge>
          </div>
          <div class="mt-1 flex items-center gap-2">
            <span class="font-mono text-[11px] text-secondary-text">
              {{ item.stockCode }}
            </span>
            <span class="h-1 w-1 rounded-full bg-subtle-hover" />
            <span class="text-[11px] text-muted-text">
              {{ formatDateTime(item.createdAt) }}
            </span>
          </div>
        </div>
      </div>
    </button>
  </div>
</template>
