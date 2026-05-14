import { onUnmounted, watch } from 'vue';
import type { TaskInfo } from '@/types/analysis';
import { useTaskStream } from './useTaskStream';

type UseDashboardLifecycleOptions = {
  loadInitialHistory: () => Promise<void>;
  refreshHistory: (silent?: boolean) => Promise<void>;
  syncTaskCreated: (task: TaskInfo) => void;
  syncTaskUpdated: (task: TaskInfo) => void;
  syncTaskFailed: (task: TaskInfo) => void;
  removeTask: (taskId: string) => void;
  enabled?: boolean;
};

export function useDashboardLifecycle({
  loadInitialHistory,
  refreshHistory,
  syncTaskCreated,
  syncTaskUpdated,
  syncTaskFailed,
  removeTask,
  enabled = true,
}: UseDashboardLifecycleOptions): void {
  const removalTimeouts: number[] = [];

  function scheduleTaskRemoval(taskId: string, delayMs: number) {
    const timeoutId = window.setTimeout(() => {
      removeTask(taskId);
      const i = removalTimeouts.indexOf(timeoutId);
      if (i >= 0) removalTimeouts.splice(i, 1);
    }, delayMs);
    removalTimeouts.push(timeoutId);
  }

  let pollInterval: number | null = null;

  function startPolling() {
    if (pollInterval !== null) return;
    pollInterval = window.setInterval(() => {
      void refreshHistory(true);
    }, 30_000);
  }

  function stopPolling() {
    if (pollInterval !== null) {
      window.clearInterval(pollInterval);
      pollInterval = null;
    }
  }

  const onVisibilityChange = () => {
    if (document.visibilityState === 'visible') {
      void refreshHistory(true);
    }
  };

  watch(
    () => enabled,
    (v) => {
      stopPolling();
      document.removeEventListener('visibilitychange', onVisibilityChange);
      if (v) {
        void loadInitialHistory();
        startPolling();
        document.addEventListener('visibilitychange', onVisibilityChange);
      }
    },
    { immediate: true },
  );

  onUnmounted(() => {
    stopPolling();
    document.removeEventListener('visibilitychange', onVisibilityChange);
    removalTimeouts.forEach((id) => window.clearTimeout(id));
  });

  useTaskStream({
    onTaskCreated: syncTaskCreated,
    onTaskStarted: syncTaskUpdated,
    onTaskProgress: syncTaskUpdated,
    onTaskCompleted: (task) => {
      syncTaskUpdated(task);
      void refreshHistory(true);
      scheduleTaskRemoval(task.taskId, 2_000);
    },
    onTaskFailed: (task) => {
      syncTaskFailed(task);
      scheduleTaskRemoval(task.taskId, 5_000);
    },
    onError: () => {
      console.warn('SSE connection disconnected, reconnecting...');
    },
    enabled,
  });
}

export default useDashboardLifecycle;
