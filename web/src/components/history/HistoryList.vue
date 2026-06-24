<script setup lang="ts">
import Pagination from '@/components/common/Pagination.vue';
import ScrollArea from '@/components/common/ScrollArea.vue';
import DashboardPanelHeader from '@/components/dashboard/DashboardPanelHeader.vue';
import DashboardStateBlock from '@/components/dashboard/DashboardStateBlock.vue';
import HistoryListItem from '@/components/history/HistoryListItem.vue';
import type { HistoryItem } from '@/types/analysis';
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    items: HistoryItem[];
    isLoading: boolean;
    currentPage: number;
    totalPages: number;
    totalCount: number;
    selectedId?: number;
    fitHeight?: boolean;
    class?: string;
  }>(),
  {
    fitHeight: false,
    class: '',
  },
);

const emit = defineEmits<{
  itemClick: [recordId: number];
  pageChange: [page: number];
}>();

const scrollAreaClass = computed(() => (props.fitHeight ? 'min-h-0 flex-none' : 'min-h-0 flex-1'));
const viewportClassName = computed(() =>
  props.fitHeight ? 'h-auto max-h-[calc(100vh-10rem)] p-4' : 'p-4',
);
</script>

<template>
  <aside :class="`glass-card flex flex-col overflow-hidden ${props.class}`">
    <ScrollArea
      :viewport-class-name="viewportClassName"
      test-id="home-history-list-scroll"
      :class="scrollAreaClass"
    >
      <div class="mb-4">
        <DashboardPanelHeader class="mb-1" title-class-name="text-sm font-medium" heading-class-name="items-center">
          <template #leading>
            <svg class="h-4 w-4 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </template>
          <template #title>历史分析</template>
        </DashboardPanelHeader>
      </div>

      <DashboardStateBlock
        v-if="isLoading"
        compact
        loading
        title="加载历史记录中..."
      />
      <DashboardStateBlock
        v-else-if="items.length === 0"
        title="暂无历史分析记录"
        description="完成首次分析后，这里会保留最近结果。"
      >
        <template #icon>
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="1.5"
              d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
        </template>
      </DashboardStateBlock>
      <div v-else class="space-y-2">
        <HistoryListItem
          v-for="item in items"
          :key="item.id"
          :item="item"
          :is-viewing="selectedId === item.id"
          @select="emit('itemClick', item.id)"
        />

        <div v-if="totalPages > 1" class="space-y-2 pt-3">
          <Pagination
            :current-page="currentPage"
            :total-pages="totalPages"
            class="!gap-1"
            @page-change="emit('pageChange', $event)"
          />
          <p class="text-center text-[10px] text-muted-text">
            共 {{ totalCount }} 条 · 第 {{ currentPage }} / {{ totalPages }} 页
          </p>
        </div>
      </div>
    </ScrollArea>
  </aside>
</template>
