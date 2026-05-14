import type { Ref } from 'vue';
import { onMounted, onUnmounted, ref } from 'vue';
import { analysisApi } from '@/api/analysis';
import type { TaskInfo } from '@/types/analysis';

export type SSEEventType =
  | 'connected'
  | 'task_created'
  | 'task_started'
  | 'task_progress'
  | 'task_completed'
  | 'task_failed'
  | 'heartbeat';

export interface SSEEvent {
  type: SSEEventType;
  task?: TaskInfo;
  timestamp?: string;
}

export interface UseTaskStreamOptions {
  onTaskCreated?: (task: TaskInfo) => void;
  onTaskStarted?: (task: TaskInfo) => void;
  onTaskCompleted?: (task: TaskInfo) => void;
  onTaskProgress?: (task: TaskInfo) => void;
  onTaskFailed?: (task: TaskInfo) => void;
  onConnected?: () => void;
  onError?: (error: Event) => void;
  autoReconnect?: boolean;
  reconnectDelay?: number;
  enabled?: boolean;
}

export interface UseTaskStreamResult {
  isConnected: Ref<boolean>;
  reconnect: () => void;
  disconnect: () => void;
}

function toCamelCase(data: Record<string, unknown>): TaskInfo {
  return {
    taskId: data.task_id as string,
    stockCode: data.stock_code as string,
    stockName: data.stock_name as string | undefined,
    status: data.status as TaskInfo['status'],
    progress: data.progress as number,
    message: data.message as string | undefined,
    reportType: data.report_type as string,
    createdAt: data.created_at as string,
    startedAt: data.started_at as string | undefined,
    completedAt: data.completed_at as string | undefined,
    error: data.error as string | undefined,
    originalQuery: data.original_query as string | undefined,
    selectionSource: data.selection_source as string | undefined,
  };
}

export function useTaskStream(options: UseTaskStreamOptions = {}): UseTaskStreamResult {
  const isConnected = ref(false);
  let eventSource: EventSource | null = null;
  let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;

  const callbacks = {
    onTaskCreated: options.onTaskCreated,
    onTaskStarted: options.onTaskStarted,
    onTaskCompleted: options.onTaskCompleted,
    onTaskProgress: options.onTaskProgress,
    onTaskFailed: options.onTaskFailed,
    onConnected: options.onConnected,
    onError: options.onError,
  };

  const autoReconnect = options.autoReconnect ?? true;
  const reconnectDelay = options.reconnectDelay ?? 3000;

  function setCallbacks() {
    callbacks.onTaskCreated = options.onTaskCreated;
    callbacks.onTaskStarted = options.onTaskStarted;
    callbacks.onTaskCompleted = options.onTaskCompleted;
    callbacks.onTaskProgress = options.onTaskProgress;
    callbacks.onTaskFailed = options.onTaskFailed;
    callbacks.onConnected = options.onConnected;
    callbacks.onError = options.onError;
  }

  function parseEventData(eventData: string): TaskInfo | null {
    try {
      const data = JSON.parse(eventData) as Record<string, unknown>;
      return toCamelCase(data);
    } catch (e) {
      console.error('Failed to parse SSE event data:', e);
      return null;
    }
  }

  function clearReconnect() {
    if (reconnectTimeout !== null) {
      clearTimeout(reconnectTimeout);
      reconnectTimeout = null;
    }
  }

  function connect() {
    setCallbacks();
    if (eventSource) {
      eventSource.close();
    }

    const url = analysisApi.getTaskStreamUrl();
    const es = new EventSource(url, { withCredentials: true });
    eventSource = es;

    es.addEventListener('connected', () => {
      isConnected.value = true;
      callbacks.onConnected?.();
    });

    es.addEventListener('task_created', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacks.onTaskCreated?.(task);
    });

    es.addEventListener('task_started', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacks.onTaskStarted?.(task);
    });

    es.addEventListener('task_progress', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacks.onTaskProgress?.(task);
    });

    es.addEventListener('task_completed', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacks.onTaskCompleted?.(task);
    });

    es.addEventListener('task_failed', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacks.onTaskFailed?.(task);
    });

    es.addEventListener('heartbeat', () => {});

    es.onerror = (error) => {
      isConnected.value = false;
      callbacks.onError?.(error);

      if (autoReconnect && options.enabled !== false) {
        es.close();
        reconnectTimeout = setTimeout(() => {
          connect();
        }, reconnectDelay);
      }
    };
  }

  function disconnect() {
    clearReconnect();
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    queueMicrotask(() => {
      isConnected.value = false;
    });
  }

  function reconnect() {
    disconnect();
    connect();
  }

  onMounted(() => {
    if (options.enabled !== false) {
      connect();
    }
  });

  onUnmounted(() => {
    disconnect();
  });

  return {
    isConnected,
    reconnect,
    disconnect,
  };
}
