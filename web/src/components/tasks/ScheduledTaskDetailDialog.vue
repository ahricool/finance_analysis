<script setup lang="ts">
import LoadingButton from '@/components/app/LoadingButton.vue';
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
import TaskDetailField from '@/components/tasks/TaskDetailField.vue';
import {
  formatDuration,
  isJobInFlight,
  runStatusLabel,
  runStatusVariant,
  schedulerStatusLabel,
  schedulerStatusVariant,
} from '@/components/tasks/taskPresentation';
import type { ScheduledSyncMode, ScheduledTask } from '@/types/tasks';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';

const props = defineProps<{
  job: ScheduledTask | null;
  running: boolean;
}>();

const emit = defineEmits<{
  'update:open': [open: boolean];
  run: [job: ScheduledTask, syncMode: ScheduledSyncMode | null];
}>();

function close() {
  emit('update:open', false);
}

function busy(job: ScheduledTask): boolean {
  return props.running || isJobInFlight(job);
}
</script>

<template>
  <Dialog
    :open="!!job"
    @update:open="emit('update:open', $event)"
  >
    <DialogScrollContent
      v-if="job"
      class="max-w-xl"
      data-testid="scheduled-task-detail"
    >
      <DialogHeader>
        <DialogTitle>{{ job.name }}</DialogTitle>
        <DialogDescription>
          {{ job.description || '查看调度信息、最近执行结果，并在需要时手动执行。' }}
        </DialogDescription>
      </DialogHeader>

      <div class="space-y-6">
        <section class="space-y-3">
          <h3 class="text-sm font-semibold">
            基本信息
          </h3>
          <dl class="grid gap-4 sm:grid-cols-2">
            <TaskDetailField label="任务名称">
              {{ job.name }}
            </TaskDetailField>
            <TaskDetailField
              label="任务类型"
              mono
            >
              {{ job.taskType }}
            </TaskDetailField>
            <TaskDetailField
              class="sm:col-span-2"
              label="说明"
            >
              {{ job.description || '—' }}
            </TaskDetailField>
            <TaskDetailField
              class="sm:col-span-2"
              label="Job ID"
              mono
            >
              {{ job.jobId }}
            </TaskDetailField>
          </dl>
        </section>

        <section class="space-y-3">
          <h3 class="text-sm font-semibold">
            调度信息
          </h3>
          <dl class="grid gap-4 sm:grid-cols-2">
            <TaskDetailField label="调度规则">
              {{ job.schedule }}
            </TaskDetailField>
            <TaskDetailField
              label="时区"
              mono
            >
              {{ job.timezone }}
            </TaskDetailField>
            <TaskDetailField label="调度状态">
              <Badge :variant="schedulerStatusVariant(job.schedulerStatus)">
                {{ schedulerStatusLabel(job.schedulerStatus) }}
              </Badge>
            </TaskDetailField>
            <TaskDetailField label="下次执行">
              {{ formatDateTimeInDisplayTimezone(job.nextRunTime) }}
            </TaskDetailField>
          </dl>
        </section>

        <section class="space-y-3">
          <h3 class="text-sm font-semibold">
            最近执行
          </h3>
          <dl
            v-if="job.latestRun"
            class="grid gap-4 sm:grid-cols-2"
          >
            <TaskDetailField label="状态">
              <Badge :variant="runStatusVariant(job.latestRun.status)">
                {{ runStatusLabel(job.latestRun.status) }}
              </Badge>
            </TaskDetailField>
            <TaskDetailField label="耗时">
              {{ formatDuration(job.latestRun.durationSeconds) }}
            </TaskDetailField>
            <TaskDetailField label="开始时间">
              {{ formatDateTimeInDisplayTimezone(job.latestRun.startedAt) }}
            </TaskDetailField>
            <TaskDetailField label="结束时间">
              {{ formatDateTimeInDisplayTimezone(job.latestRun.finishedAt) }}
            </TaskDetailField>
            <TaskDetailField
              class="sm:col-span-2"
              label="结果"
            >
              {{ job.latestRun.message || '—' }}
            </TaskDetailField>
            <TaskDetailField
              class="sm:col-span-2"
              label="Task ID"
              mono
            >
              {{ job.latestRun.taskId }}
            </TaskDetailField>
          </dl>
          <p
            v-else
            class="text-sm text-muted-foreground"
          >
            尚未执行过。
          </p>
        </section>
      </div>

      <DialogFooter class="gap-2 sm:justify-between">
        <Button
          variant="outline"
          @click="close"
        >
          关闭
        </Button>
        <div
          v-if="job.allowManualRun"
          class="flex flex-wrap justify-end gap-2"
        >
          <template v-if="job.syncModes.length">
            <LoadingButton
              variant="outline"
              :loading="running"
              :disabled="busy(job)"
              @click="emit('run', job, 'incremental')"
            >
              增量同步
            </LoadingButton>
            <Button
              variant="outline"
              :disabled="busy(job)"
              @click="emit('run', job, 'full')"
            >
              全量同步
            </Button>
          </template>
          <LoadingButton
            v-else
            :loading="running"
            :disabled="busy(job)"
            @click="emit('run', job, null)"
          >
            立即执行
          </LoadingButton>
        </div>
      </DialogFooter>
    </DialogScrollContent>
  </Dialog>
</template>
