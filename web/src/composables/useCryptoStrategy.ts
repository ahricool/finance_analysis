import { onMounted, onUnmounted, ref, shallowRef, watch, type Ref } from 'vue';
import { cryptoApi } from '@/api/crypto';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import type { CryptoOverview, CryptoSnapshot, CryptoPerformance } from '@/types/crypto';

export function useCryptoStrategy(range?: Ref<{ start: string; end: string } | null>) {
  const performance = shallowRef<CryptoPerformance | null>(null);
  const performanceError = shallowRef<ParsedApiError | null>(null);
  const markers = shallowRef<CryptoSnapshot[]>([]);
  const markerError = shallowRef<ParsedApiError | null>(null);
  let markerRequest = 0;
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
  async function refreshPerformance() {
    try {
      const value = await cryptoApi.performance();
      if (!stopped) { performance.value = value; performanceError.value = null; }
    } catch (reason) { if (!stopped) performanceError.value = getParsedApiError(reason); }
  }
  async function refreshMarkers() {
    const version = ++markerRequest;
    if (!range?.value) { markers.value = []; return; }
    try {
      const value = await cryptoApi.signals(range.value);
      if (!stopped && version === markerRequest) { markers.value = value.items; markerError.value = null; }
    } catch (reason) { if (!stopped && version === markerRequest) markerError.value = getParsedApiError(reason); }
  }
  if (range) watch(() => range.value ? `${range.value.start}/${range.value.end}` : '', () => { markers.value = []; void refreshMarkers(); });
  onMounted(() => { void refresh(); void refreshPerformance(); void refreshMarkers();
    timer = setInterval(() => { void refresh(); void refreshPerformance(); void refreshMarkers(); }, 60_000); });
  onUnmounted(() => { stopped = true; clearInterval(timer); });
  return { overview, signals, loading, error, refresh, performance, performanceError, refreshPerformance, markers, markerError, refreshMarkers };
}
