<script setup lang="ts">
import Badge from '@/components/common/Badge.vue';
import Card from '@/components/common/Card.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import DashboardPanelHeader from '@/components/dashboard/DashboardPanelHeader.vue';
import type { TaskInfo } from '@/types/analysis';
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    tasks: TaskInfo[];
    visible?: boolean;
    title?: string;
    class?: string;
  }>(),
  {
    visible: true,
    title: '分析任务',
    class: '',
  },
);

const activeTasks = computed(() =>
  props.tasks.filter((t) => t.status === 'pending' || t.status === 'processing'),
);

const pendingCount = computed(() => activeTasks.value.filter((t) => t.status === 'pending').length);
const processingCount = computed(() =>
  activeTasks.value.filter((t) => t.status === 'processing').length,
);

const showPanel = computed(() => props.visible && activeTasks.value.length > 0);
</script>

<template>
  <Card
    v-if="showPanel"
    variant="bordered"
    padding="none"
    :class="`home-panel-card overflow-hidden ${props.class}`"
  >
    <div class="border-b border-subtle px-3 py-3">
      <DashboardPanelHeader class="mb-0" title-class-name="text-sm font-medium" heading-class-name="items-center">
        <template #leading>
          <svg class="h-4 w-4 text-cyan" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
            />
          </svg>
        </template>
        <template #title>{{ title }}</template>
        <template #actions>
          <div class="flex items-center gap-2 text-xs text-muted-text">
            <span v-if="processingCount > 0" class="flex items-center gap-1">
              <StatusDot tone="info" pulse class="h-1.5 w-1.5" aria-label="进行中任务" />
              {{ processingCount }} 进行中
            </span>
            <span v-if="pendingCount > 0" class="flex items-center gap-1">
              <StatusDot tone="neutral" class="h-1.5 w-1.5" aria-label="等待中任务" />
              {{ pendingCount }} 等待中
            </span>
          </div>
        </template>
      </DashboardPanelHeader>
    </div>

    <div class="max-h-64 overflow-y-auto p-2">
      <div class="space-y-2">
        <div
          v-for="task in activeTasks"
          :key="task.taskId"
          class="home-subpanel flex items-center gap-3 px-3 py-2.5"
        >
          <div class="shrink-0">
            <StatusDot
              v-if="task.status === 'processing'"
              tone="info"
              pulse
              class="h-2.5 w-2.5"
              aria-label="任务进行中"
            />
            <StatusDot
              v-else-if="task.status === 'pending'"
              tone="neutral"
              class="h-2.5 w-2.5"
              aria-label="任务等待中"
            />
          </div>

          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="truncate text-sm font-medium text-foreground">
                {{ task.stockName || task.stockCode }}
              </span>
              <span class="text-xs text-muted-text">
                {{ task.stockCode }}
              </span>
            </div>
            <p v-if="task.message" class="mt-0.5 truncate text-xs text-secondary-text">
              {{ task.message }}
            </p>
            <div class="mt-2 flex items-center gap-2">
              <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-white/8">
                <div
                  class="h-full rounded-full bg-cyan transition-[width] duration-300 ease-out"
                  :style="{ width: `${Math.max(0, Math.min(100, task.progress || 0))}%` }"
                />
              </div>
              <span class="shrink-0 tabular-nums text-[11px] text-muted-text">
                {{ Math.max(0, Math.min(100, task.progress || 0)) }}%
              </span>
            </div>
          </div>

          <div class="flex-shrink-0">
            <Badge
              :variant="task.status === 'processing' ? 'info' : 'default'"
              class="min-w-[4.75rem] justify-center gap-1.5 shadow-none"
              :aria-label="`任务状态：${task.status === 'processing' ? '分析中' : '等待中'}`"
            >
              <StatusDot
                :tone="task.status === 'processing' ? 'info' : 'neutral'"
                :pulse="task.status === 'processing'"
                class="h-1.5 w-1.5"
              />
              {{ task.status === 'processing' ? '分析中' : '等待中' }}
            </Badge>
          </div>
        </div>
      </div>
    </div>
  </Card>
</template>
