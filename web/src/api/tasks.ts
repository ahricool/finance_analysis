import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  ScheduledRunAccepted,
  ScheduledSyncMode,
  ScheduledTasksResponse,
  TaskRunDetail,
  TaskRunsResponse,
} from '@/types/tasks';

export type TaskRunQuery = {
  page?: number;
  pageSize?: number;
  status?: string;
  taskType?: string;
  source?: string;
  triggerSource?: string;
  schedulerJobId?: string;
  keyword?: string;
  startedFrom?: string;
  startedTo?: string;
  uid?: number;
};

function toParams(query: TaskRunQuery = {}) {
  return {
    page: query.page,
    page_size: query.pageSize,
    status: query.status || undefined,
    task_type: query.taskType || undefined,
    source: query.source || undefined,
    trigger_source: query.triggerSource || undefined,
    scheduler_job_id: query.schedulerJobId || undefined,
    keyword: query.keyword || undefined,
    started_from: query.startedFrom || undefined,
    started_to: query.startedTo || undefined,
    uid: query.uid,
  };
}

export const tasksApi = {
  async getScheduledTasks(): Promise<ScheduledTasksResponse> {
    const { data } = await apiClient.get<Record<string, unknown>>('/api/v1/tasks/scheduled');
    return toCamelCase<ScheduledTasksResponse>(data);
  },

  async runScheduledTask(jobId: string, syncMode?: ScheduledSyncMode): Promise<ScheduledRunAccepted> {
    const { data } = await apiClient.post<Record<string, unknown>>(
      `/api/v1/tasks/scheduled/${encodeURIComponent(jobId)}/run`,
      syncMode ? { sync_mode: syncMode } : {},
    );
    return toCamelCase<ScheduledRunAccepted>(data);
  },

  async getTaskRuns(query?: TaskRunQuery): Promise<TaskRunsResponse> {
    const { data } = await apiClient.get<Record<string, unknown>>('/api/v1/tasks', {
      params: toParams(query),
    });
    return toCamelCase<TaskRunsResponse>(data);
  },

  async getTaskRunDetail(taskId: string): Promise<TaskRunDetail> {
    const { data } = await apiClient.get<Record<string, unknown>>(
      `/api/v1/tasks/${encodeURIComponent(taskId)}`,
    );
    return toCamelCase<TaskRunDetail>(data);
  },
};
