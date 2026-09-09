<script setup lang="ts">
import type { ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogScrollContent,
  DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import TaskDetailField from '@/components/tasks/TaskDetailField.vue';
import TaskJsonBlock from '@/components/tasks/TaskJsonBlock.vue';
import {
  formatDuration,
  formatJson,
  hasDisplayValue,
  runStatusLabel,
  runStatusVariant,
  sourceLabel,
  triggerLabel,
} from '@/components/tasks/taskPresentation';
import type { TaskRunDetail } from '@/types/tasks';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import { Copy } from 'lucide-vue-next';
import { toast } from 'vue-sonner';

defineProps<{
  open: boolean;
  detail: TaskRunDetail | null;
  loading: boolean;
  error: ParsedApiError | null;
  isAdmin: boolean;
}>();

const emit = defineEmits<{
  'update:open': [open: boolean];
  dismissError: [];
}>();

async function copyText(value?: string | null) {
  if (!value) return;
  await navigator.clipboard.writeText(value);
  toast.success('已复制');
}
</script>

<template>
  <Dialog
    :open="open"
    @update:open="emit('update:open', $event)"
  >
    <DialogScrollContent
      class="max-w-2xl"
      data-testid="task-run-detail"
    >
      <DialogHeader>
        <DialogTitle>
          {{ detail?.taskName || detail?.taskType || '执行详情' }}
        </DialogTitle>
        <DialogDescription>
          查看这次执行的状态、时间、结果和调试信息。
        </DialogDescription>
      </DialogHeader>

      <div
        v-if="loading"
        class="space-y-3"
      >
        <Skeleton
          v-for="index in 5"
          :key="index"
          class="h-16 w-full"
        />
      </div>
      <ApiErrorAlert
        v-else-if="error"
        :error="error"
        @dismiss="emit('dismissError')"
      />
      <div
        v-else-if="detail"
        class="space-y-6"
      >
        <section class="space-y-3">
          <h3 class="text-sm font-semibold">
            基本信息
          </h3>
          <dl class="grid gap-4 sm:grid-cols-2">
            <TaskDetailField label="任务">
              {{ detail.taskName || detail.taskType }}
            </TaskDetailField>
            <TaskDetailField
              label="任务类型"
              mono
            >
              {{ detail.taskType }}
            </TaskDetailField>
            <TaskDetailField
              class="sm:col-span-2"
              label="Task ID"
              mono
            >
              <span class="inline-flex max-w-full items-start gap-2">
                <span class="min-w-0 break-all">{{ detail.taskId }}</span>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  class="shrink-0"
                  aria-label="复制 Task ID"
                  @click="copyText(detail.taskId)"
                >
                  <Copy class="size-3.5" />
                </Button>
              </span>
            </TaskDetailField>
          </dl>
        </section>

        <section class="space-y-3">
          <h3 class="text-sm font-semibold">
            执行状态
          </h3>
          <dl class="grid gap-4 sm:grid-cols-2">
            <TaskDetailField label="状态">
              <Badge :variant="runStatusVariant(detail.status)">
                {{ runStatusLabel(detail.status) }}
              </Badge>
            </TaskDetailField>
            <TaskDetailField label="耗时">
              {{ formatDuration(detail.durationSeconds) }}
            </TaskDetailField>
            <TaskDetailField
              v-if="hasDisplayValue(detail.message)"
              class="sm:col-span-2"
              label="结果摘要"
            >
              {{ detail.message }}
            </TaskDetailField>
          </dl>
        </section>

        <section class="space-y-3">
          <h3 class="text-sm font-semibold">
            执行时间
          </h3>
          <dl class="grid gap-4 sm:grid-cols-2">
            <TaskDetailField label="创建时间">
              {{ formatDateTimeInDisplayTimezone(detail.createdAt) }}
            </TaskDetailField>
            <TaskDetailField label="开始时间">
              {{ formatDateTimeInDisplayTimezone(detail.startedAt) }}
            </TaskDetailField>
            <TaskDetailField label="结束时间">
              {{ formatDateTimeInDisplayTimezone(detail.finishedAt) }}
            </TaskDetailField>
            <TaskDetailField label="更新时间">
              {{ formatDateTimeInDisplayTimezone(detail.updatedAt) }}
            </TaskDetailField>
          </dl>
        </section>

        <section
          v-if="hasDisplayValue(detail.error)"
          class="space-y-2"
        >
          <h3 class="text-sm font-semibold text-destructive">
            错误信息
          </h3>
          <pre class="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-destructive/20 bg-destructive/5 p-3 font-mono text-xs text-destructive">{{ detail.error }}</pre>
        </section>

        <TaskJsonBlock
          v-if="hasDisplayValue(detail.payload)"
          title="Payload"
          :content="formatJson(detail.payload)"
        />
        <TaskJsonBlock
          v-if="hasDisplayValue(detail.result)"
          title="Result"
          :content="formatJson(detail.result)"
        />
        <TaskJsonBlock
          v-if="isAdmin && hasDisplayValue(detail.taskLog)"
          title="Task Log"
          :content="String(detail.taskLog)"
        />

        <section class="space-y-3">
          <h3 class="text-sm font-semibold">
            调试字段
          </h3>
          <dl class="grid gap-4 sm:grid-cols-2">
            <TaskDetailField label="来源">
              {{ sourceLabel(detail.source) }}
            </TaskDetailField>
            <TaskDetailField label="触发方式">
              {{ triggerLabel(detail.triggerSource) }}
            </TaskDetailField>
            <TaskDetailField
              v-if="detail.schedulerJobId"
              class="sm:col-span-2"
              label="Scheduler Job ID"
              mono
            >
              {{ detail.schedulerJobId }}
            </TaskDetailField>
            <TaskDetailField
              v-if="detail.parentTaskId"
              class="sm:col-span-2"
              label="Parent Task ID"
              mono
            >
              {{ detail.parentTaskId }}
            </TaskDetailField>
            <TaskDetailField label="重试次数">
              {{ detail.retryCount }}
            </TaskDetailField>
            <TaskDetailField
              v-if="detail.user"
              label="所属用户"
            >
              {{ detail.user.username }} · {{ detail.user.email }}
            </TaskDetailField>
            <TaskDetailField
              v-else-if="detail.uid != null"
              label="UID"
            >
              {{ detail.uid }}
            </TaskDetailField>
            <TaskDetailField
              v-if="detail.triggeredByUser"
              label="触发人"
            >
              {{ detail.triggeredByUser.username }}
            </TaskDetailField>
          </dl>
        </section>
      </div>

      <DialogFooter>
        <Button
          variant="outline"
          @click="emit('update:open', false)"
        >
          关闭
        </Button>
      </DialogFooter>
    </DialogScrollContent>
  </Dialog>
</template>
