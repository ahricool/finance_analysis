export type TaskStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'retrying'
  | 'cancelled';

export type SchedulerStatus = 'active' | 'paused' | 'running' | 'unavailable';
export type ScheduledSyncMode = 'incremental' | 'full';

export type TaskUserSummary = {
  uid: number;
  username: string;
  email: string;
  role: string;
};

export type TaskRun = {
  id: number;
  taskId: string;
  taskName?: string | null;
  taskType: string;
  uid?: number | null;
  user?: TaskUserSummary | null;
  source: string;
  triggerSource?: string | null;
  triggeredByUid?: number | null;
  triggeredByUser?: TaskUserSummary | null;
  status: TaskStatus;
  progress: number;
  message?: string | null;
  schedulerJobId?: string | null;
  parentTaskId?: string | null;
  retryCount: number;
  createdAt?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  updatedAt?: string | null;
  durationSeconds?: number | null;
};

export type TaskRunDetail = TaskRun & {
  payload?: unknown;
  result?: unknown;
  error?: string | null;
  taskLog?: string | null;
};

export type TaskRunsResponse = {
  items: TaskRun[];
  total: number;
  page: number;
  pageSize: number;
  statistics: Record<TaskStatus, number>;
};

export type ScheduledTaskLatestRun = {
  taskId: string;
  status: TaskStatus;
  startedAt?: string | null;
  finishedAt?: string | null;
  durationSeconds?: number | null;
  message?: string | null;
};

export type ScheduledTask = {
  jobId: string;
  name: string;
  description: string;
  taskType: string;
  schedule: string;
  timezone: string;
  schedulerStatus: SchedulerStatus;
  nextRunTime?: string | null;
  allowManualRun: boolean;
  syncModes: ScheduledSyncMode[];
  latestRun?: ScheduledTaskLatestRun | null;
};

export type ScheduledTasksResponse = {
  items: ScheduledTask[];
};

export type ScheduledRunAccepted = {
  taskId: string;
  jobId: string;
  status: 'pending';
  message: string;
  syncMode?: ScheduledSyncMode | null;
};
