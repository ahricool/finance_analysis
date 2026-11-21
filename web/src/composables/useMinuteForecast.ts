import { onMounted, shallowRef, watch } from 'vue';
import { fetchMinuteForecast, type MinuteForecastResponse } from '@/api/minuteForecast';

export function useMinuteForecast(symbol: () => string, active: () => boolean) {
  const result = shallowRef<MinuteForecastResponse | null>(null);
  onMounted(() => {
    watch(() => (active() ? symbol() : ''), (selected, _previous, onCleanup) => {
      result.value = null;
      if (!selected) return;
      const request = new AbortController();
      let timer: ReturnType<typeof setTimeout> | undefined;
      onCleanup(() => { request.abort(); clearTimeout(timer); });

      async function load() {
        try {
          const value = await fetchMinuteForecast(selected, request.signal);
          if (!request.signal.aborted) result.value = value;
        } catch {
          // Forecast retrieval is independent of the real-time chart and quote connection.
        } finally {
          if (!request.signal.aborted && result.value?.enabled !== false) timer = setTimeout(() => { void load(); }, 8_000);
        }
      }
      void load();
    }, { immediate: true });
  });
  return result;
}
