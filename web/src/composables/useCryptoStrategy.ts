import { onMounted, onUnmounted, ref, shallowRef } from 'vue';
import { cryptoApi } from '@/api/crypto';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import type { CryptoOverview, CryptoSnapshot } from '@/types/crypto';

export function useCryptoStrategy() {
  const overview = shallowRef<CryptoOverview | null>(null);
  const signals = shallowRef<CryptoSnapshot[]>([]);
  const loading = ref(true);
  const error = shallowRef<ParsedApiError | null>(null);
  let stopped = false;
  let pending = false;
  let timer: ReturnType<typeof setInterval>;
  async function refresh() {
    if (pending || stopped) return;
    pending = true;
    try {
      const [info, recent] = await Promise.all([cryptoApi.overview(), cryptoApi.signals()]);
      if (stopped) return;
      overview.value = info;
      signals.value = recent.items;
      error.value = null;
    } catch (reason) {
      if (!stopped) error.value = getParsedApiError(reason);
    } finally {
      pending = false;
      loading.value = false;
    }
  }
  onMounted(() => { void refresh(); timer = setInterval(() => void refresh(), 60_000); });
  onUnmounted(() => { stopped = true; clearInterval(timer); });
  return { overview, signals, loading, error, refresh };
}
