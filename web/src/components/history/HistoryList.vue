<script setup lang="ts">
import Pagination from '@/components/app/AppPagination.vue';
import HistoryListItem from '@/components/history/HistoryListItem.vue';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import type { HistoryItem } from '@/types/analysis';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { History } from 'lucide-vue-next';

const props = withDefaults(
  defineProps<{
    items: HistoryItem[];
    isLoading: boolean;
    currentPage: number;
    totalPages: number;
    totalCount: number;
    selectedId?: number;
    class?: string;
  }>(),
  {
    selectedId: undefined,
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
        <History class="size-4 text-muted-foreground" />历史分析
      </CardTitle>
      <CardDescription>共 {{ totalCount }} 条最近报告</CardDescription>
    </CardHeader>
    <CardContent class="min-h-0 flex-1 p-0">
      <ScrollArea
        data-testid="analysis-history-list-scroll"
        class="h-full"
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
          <Empty
            v-else-if="items.length === 0"
            class="border-0 py-10"
          >
            <EmptyHeader>
              <EmptyMedia variant="icon"><History /></EmptyMedia>
              <EmptyTitle>暂无历史分析记录</EmptyTitle>
              <EmptyDescription>完成首次分析后，这里会保留最近结果。</EmptyDescription>
            </EmptyHeader>
          </Empty>
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
        @page-change="emit('pageChange', $event)"
      />
      <p class="text-center text-xs text-muted-foreground">
        第 {{ currentPage }} / {{ totalPages }} 页
      </p>
    </CardFooter>
  </Card>
</template>
