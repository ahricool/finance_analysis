<script setup lang="ts">
import Badge from '@/components/common/Badge.vue';
import Button from '@/components/common/Button.vue';
import ScrollArea from '@/components/common/ScrollArea.vue';
import DashboardPanelHeader from '@/components/dashboard/DashboardPanelHeader.vue';
import DashboardStateBlock from '@/components/dashboard/DashboardStateBlock.vue';
import HistoryListItem from '@/components/history/HistoryListItem.vue';
import type { HistoryItem } from '@/types/analysis';
import { computed, onMounted, onUnmounted, ref, useId, watch } from 'vue';

const props = withDefaults(
  defineProps<{
    items: HistoryItem[];
    isLoading: boolean;
    isLoadingMore: boolean;
    hasMore: boolean;
    selectedId?: number;
    selectedIds: Set<number>;
    isDeleting?: boolean;
    fitHeight?: boolean;
    class?: string;
  }>(),
  {
    isDeleting: false,
    fitHeight: false,
    class: '',
  },
);

const emit = defineEmits<{
  itemClick: [recordId: number];
  loadMore: [];
  toggleItemSelection: [recordId: number];
  toggleSelectAll: [];
  deleteSelected: [];
}>();

const scrollAreaRef = ref<{ viewportEl: HTMLDivElement | null } | null>(null);
const loadMoreTriggerRef = ref<HTMLDivElement | null>(null);
const selectAllRef = ref<HTMLInputElement | null>(null);
const selectAllId = useId();

const selectedCount = computed(() => props.items.filter((item) => props.selectedIds.has(item.id)).length);
const allVisibleSelected = computed(
  () => props.items.length > 0 && selectedCount.value === props.items.length,
);
const someVisibleSelected = computed(
  () => selectedCount.value > 0 && !allVisibleSelected.value,
);
const scrollAreaClass = computed(() => (props.fitHeight ? 'min-h-0 flex-none' : 'min-h-0 flex-1'));
const viewportClassName = computed(() =>
  props.fitHeight ? 'h-auto max-h-[calc(100vh-10rem)] p-4' : 'p-4',
);

let observer: IntersectionObserver | null = null;

function attachObserver() {
  observer?.disconnect();
  const trigger = loadMoreTriggerRef.value;
  const container = scrollAreaRef.value?.viewportEl;
  if (!trigger || !container) return;

  observer = new IntersectionObserver(
    (entries) => {
      const target = entries[0];
      if (
        target &&
        target.isIntersecting &&
        props.hasMore &&
        !props.isLoading &&
        !props.isLoadingMore
      ) {
        if (container.scrollHeight > container.clientHeight) {
          emit('loadMore');
        }
      }
    },
    { root: container, rootMargin: '20px', threshold: 0.1 },
  );
  observer.observe(trigger);
}

watch(
  () => [props.items.length, props.hasMore, props.isLoading, props.isLoadingMore],
  () => {
    requestAnimationFrame(() => attachObserver());
  },
);

onMounted(() => {
  requestAnimationFrame(() => attachObserver());
});

watch(someVisibleSelected, (v) => {
  if (selectAllRef.value) {
    selectAllRef.value.indeterminate = v;
  }
});

onUnmounted(() => {
  observer?.disconnect();
});
</script>

<template>
  <aside :class="`glass-card flex flex-col overflow-hidden ${props.class}`">
    <ScrollArea
      ref="scrollAreaRef"
      :viewport-class-name="viewportClassName"
      test-id="home-history-list-scroll"
      :class="scrollAreaClass"
    >
      <div class="mb-4 space-y-3">
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
          <template v-if="selectedCount > 0" #actions>
            <Badge
              variant="info"
              size="sm"
              class="history-selection-badge animate-in fade-in zoom-in duration-200"
            >
              已选 {{ selectedCount }}
            </Badge>
          </template>
        </DashboardPanelHeader>

        <div v-if="items.length > 0" class="flex items-center gap-2">
          <label
            class="flex flex-1 cursor-pointer items-center gap-2 rounded-lg px-2 py-1"
            :for="selectAllId"
          >
            <input
              :id="selectAllId"
              ref="selectAllRef"
              type="checkbox"
              :checked="allVisibleSelected"
              :disabled="isDeleting"
              aria-label="全选当前已加载历史记录"
              class="history-select-all-checkbox h-3.5 w-3.5 cursor-pointer bg-transparent accent-primary focus:ring-primary/30 disabled:opacity-50"
              @change="emit('toggleSelectAll')"
            />
            <span class="select-none text-[11px] text-muted-text">全选当前</span>
          </label>
          <Button
            variant="danger-subtle"
            size="xsm"
            :disabled="selectedCount === 0 || isDeleting"
            :is-loading="isDeleting"
            class="history-batch-delete-button disabled:!border-transparent disabled:!bg-transparent"
            @click="emit('deleteSelected')"
          >
            {{ isDeleting ? '删除中' : '删除' }}
          </Button>
        </div>
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
          :is-checked="selectedIds.has(item.id)"
          :isDeleting="isDeleting"
          @toggle-checked="emit('toggleItemSelection', item.id)"
          @select="emit('itemClick', item.id)"
        />

        <div ref="loadMoreTriggerRef" class="h-4" />

        <div v-if="isLoadingMore" class="flex justify-center py-4">
          <div class="home-spinner h-5 w-5 animate-spin border-2" />
        </div>

        <div v-if="!hasMore && items.length > 0" class="py-5 text-center">
          <div class="mb-3 h-px w-full bg-subtle" />
          <span class="text-[10px] uppercase tracking-[0.2em] text-secondary-text">已到底部</span>
        </div>
      </div>
    </ScrollArea>
  </aside>
</template>
