import type { BadgeVariants } from '@/components/ui/badge';
import type { ScheduledTask, SchedulerStatus, TaskStatus } from '@/types/tasks';

const BUSY_STATUSES: TaskStatus[] = ['pending', 'processing', 'retrying'];

const RUN_STATUS_LABELS: Record<TaskStatus, string> = {
  pending: '等待中',
  processing: '执行中',
  completed: '成功',
  failed: '失败',
  skipped: '已跳过',
  retrying: '重试中',
  cancelled: '已取消',
};

export const TASK_STATUS_OPTIONS: Array<{ value: TaskStatus; label: string }> = (
  Object.entries(RUN_STATUS_LABELS) as Array<[TaskStatus, string]>
).map(([value, label]) => ({ value, label }));

export const DEFAULT_RUN_STATUS_FILTERS: TaskStatus[] = TASK_STATUS_OPTIONS
  .filter((option) => option.value !== 'skipped')
  .map((option) => option.value);

export function runStatusLabel(value?: string | null): string {
  if (!value) return '从未执行';
  return RUN_STATUS_LABELS[value as TaskStatus] ?? value;
}

export function runStatusVariant(value?: string | null): BadgeVariants['variant'] {
  if (value === 'completed') return 'success';
  if (value === 'failed') return 'destructive';
  if (value === 'processing') return 'info';
  if (value === 'retrying' || value === 'pending') return 'warning';
  return 'outline';
}

export function schedulerStatusLabel(value: SchedulerStatus | string): string {
  if (value === 'active') return '正常';
  if (value === 'paused') return '暂停';
  if (value === 'running') return '执行中';
  return '不可用';
}

export function schedulerStatusVariant(value: SchedulerStatus | string): BadgeVariants['variant'] {
  if (value === 'active') return 'success';
  if (value === 'running') return 'info';
  if (value === 'paused') return 'warning';
  return 'outline';
}

export function isRunBusy(status?: string | null): boolean {
  return Boolean(status && BUSY_STATUSES.includes(status as TaskStatus));
}

export function isJobInFlight(job: ScheduledTask): boolean {
  return job.schedulerStatus === 'running' || isRunBusy(job.latestRun?.status);
}

export function jobStatusLabel(job: ScheduledTask): string {
  if (isJobInFlight(job)) return schedulerStatusLabel('running');
  return schedulerStatusLabel(job.schedulerStatus);
}

export function jobStatusVariant(job: ScheduledTask): BadgeVariants['variant'] {
  if (isJobInFlight(job)) return schedulerStatusVariant('running');
  return schedulerStatusVariant(job.schedulerStatus);
}

export function formatDuration(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return '—';
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes <= 0) return `${rest} 秒`;
  return `${minutes} 分 ${rest} 秒`;
}

export function truncateText(value?: string | null, max = 72): string {
  const text = value?.trim() ?? '';
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function sourceLabel(value?: string | null): string {
  if (value === 'celery') return '定时任务';
  if (value === 'celery_manual') return '手动执行';
  return value || '—';
}

export function triggerLabel(value?: string | null): string {
  if (value === 'scheduler') return '定时触发';
  if (value === 'manual') return '手动执行';
  if (value === 'api') return 'API 提交';
  if (value === 'bot') return 'Bot 提交';
  return value || '—';
}

export function hasDisplayValue(value: unknown): boolean {
  if (value === null || value === undefined || value === '') return false;
  return true;
}

export function formatJson(value: unknown): string {
  if (!hasDisplayValue(value)) return '—';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}
