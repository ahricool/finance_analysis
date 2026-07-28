import { onUnmounted, ref, type Ref } from 'vue';

export const CURRENT_TIME_REFRESH_INTERVAL_MS = 60_000;

export function useCurrentTime(intervalMs = CURRENT_TIME_REFRESH_INTERVAL_MS): Ref<Date> {
  const now = ref(new Date());
  const timer = window.setInterval(() => {
    now.value = new Date();
  }, intervalMs);

  onUnmounted(() => window.clearInterval(timer));
  return now;
}
