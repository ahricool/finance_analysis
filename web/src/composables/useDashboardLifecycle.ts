import { onUnmounted, watch } from 'vue';

type UseDashboardLifecycleOptions = {
  loadInitialHistory: () => Promise<void>;
  refreshHistory: (silent?: boolean) => Promise<void>;
  enabled?: boolean;
};

export function useDashboardLifecycle({
  loadInitialHistory,
  refreshHistory,
  enabled = true,
}: UseDashboardLifecycleOptions): void {
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
  });
}
