<script setup lang="ts">
import Pagination from '@/components/app/AppPagination.vue';
import DashboardStateBlock from '@/components/dashboard/DashboardStateBlock.vue';
import HistoryListItem from '@/components/history/HistoryListItem.vue';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import type { HistoryItem } from '@/types/analysis';
import { History } from 'lucide-vue-next';

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
    selectedId: undefined,
    fitHeight: false,
    class: '',
  },
);

const emit = defineEmits<{
  itemClick: [recordId: number];
  pageChange: [page: number];
}>();

</script>

<template>
  <Card :class="['flex min-h-0 flex-col overflow-hidden', props.class]">
    <CardHeader class="shrink-0">
      <CardTitle class="flex items-center gap-2 text-base">
        <History class="size-4 text-primary" />历史分析
      </CardTitle>
      <CardDescription>共 {{ totalCount }} 条最近报告</CardDescription>
    </CardHeader>
    <CardContent class="min-h-0 flex-1 p-0">
      <ScrollArea
        data-testid="analysis-history-list-scroll"
        :class="fitHeight ? 'max-h-[calc(100vh-14rem)]' : 'h-full'"
      >
        <div class="space-y-2 px-4 pb-4">
          <div
            v-if="isLoading"
            class="space-y-2"
          >
            <Skeleton
              v-for="index in 5"
              :key="index"
              class="h-16 w-full"
            />
          </div>
          <DashboardStateBlock
            v-else-if="items.length === 0"
            title="暂无历史分析记录"
            description="完成首次分析后，这里会保留最近结果。"
          >
            <template #icon>
              <History class="size-5" />
            </template>
          </DashboardStateBlock>
          <div
            v-else
            class="space-y-2"
          >
            <HistoryListItem
              v-for="item in items"
              :key="item.id"
              :item="item"
              :is-viewing="selectedId === item.id"
              @select="emit('itemClick', item.id)"
            />
          </div>
        </div>
      </ScrollArea>
    </CardContent>
    <CardFooter
      v-if="totalPages > 1"
      class="shrink-0 flex-col gap-2 border-t pt-4"
    >
      <Pagination
        :current-page="currentPage"
        :total-pages="totalPages"
        class="!gap-1"
        @page-change="emit('pageChange', $event)"
      />
      <p class="text-center text-[10px] text-muted-foreground">
        第 {{ currentPage }} / {{ totalPages }} 页
      </p>
    </CardFooter>
  </Card>
</template>
