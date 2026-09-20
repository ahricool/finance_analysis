import { onMounted, onUnmounted, ref, shallowRef, watch, type Ref } from 'vue';
import { cryptoApi } from '@/api/crypto';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import type { CryptoOverview, CryptoSnapshot, CryptoPerformance, CryptoStrategyDefinition, CryptoPerformanceSummary } from '@/types/crypto';

export function useCryptoStrategy(range?: Ref<{ start: string; end: string } | null>) {
  const selectedKey = ref('btc_breakout_v1');
  const strategies = shallowRef<CryptoStrategyDefinition[]>([]);
  const strategiesError = shallowRef<ParsedApiError | null>(null);
  const summaries = shallowRef<CryptoPerformanceSummary[]>([]);
  const performance = shallowRef<CryptoPerformance | null>(null);
  const performanceError = shallowRef<ParsedApiError | null>(null);
  const markers = shallowRef<CryptoSnapshot[]>([]);
  const markerError = shallowRef<ParsedApiError | null>(null);
  const overview = shallowRef<CryptoOverview | null>(null);
  const signals = shallowRef<CryptoSnapshot[]>([]);
  const loading = ref(true);
  const error = shallowRef<ParsedApiError | null>(null);
  let stopped = false;
  let infoRequest = 0, performanceRequest = 0, markerRequest = 0;
  let timer: ReturnType<typeof setInterval>;
  async function refresh() {
    const version = ++infoRequest;
    try {
      const [info, recent] = await Promise.all([cryptoApi.overview(selectedKey.value), cryptoApi.signals(selectedKey.value)]);
      if (stopped || version !== infoRequest) return;
      overview.value = info; signals.value = recent.items; error.value = null;
    } catch (reason) {
      if (!stopped && version === infoRequest) error.value = getParsedApiError(reason);
    } finally { if (version === infoRequest) loading.value = false; }
  }
  async function refreshPerformance() {
    const version = ++performanceRequest;
    try {
      const value = await cryptoApi.performance(selectedKey.value);
      if (!stopped && version === performanceRequest) { performance.value = value; performanceError.value = null; }
    } catch (reason) { if (!stopped && version === performanceRequest) performanceError.value = getParsedApiError(reason); }
  }
  async function refreshMarkers() {
    const version = ++markerRequest;
    if (!range?.value) { markers.value = []; return; }
    try {
      const value = await cryptoApi.signals(selectedKey.value, range.value);
      if (!stopped && version === markerRequest) { markers.value = value.items; markerError.value = null; }
    } catch (reason) { if (!stopped && version === markerRequest) markerError.value = getParsedApiError(reason); }
  }
  async function refreshStrategies() {
    try {
      const items = await cryptoApi.strategies();
      if (stopped) return;
      strategies.value = items;
      strategiesError.value = null;
      if (items.filter(item => item.enabled).length >= 2) {
        const values = await cryptoApi.summaries();
        if (!stopped) summaries.value = values;
      } else summaries.value = [];
    } catch (reason) { if (!stopped) strategiesError.value = getParsedApiError(reason); }
  }
  const refreshSelected = () => { void refresh(); void refreshPerformance(); void refreshMarkers(); };
  watch(selectedKey, () => {
    overview.value = null; signals.value = []; performance.value = null; markers.value = [];
    error.value = null; performanceError.value = null; markerError.value = null; loading.value = true;
    refreshSelected();
  });
  if (range) watch(() => range.value ? `${range.value.start}/${range.value.end}` : '', () => { markers.value = []; void refreshMarkers(); });
  onMounted(() => { refreshSelected(); void refreshStrategies();
    timer = setInterval(() => { refreshSelected(); void refreshStrategies(); }, 60_000); });
  onUnmounted(() => { stopped = true; clearInterval(timer); });
  return { selectedKey, strategies, strategiesError, refreshStrategies, summaries, overview, signals, loading, error, refresh, performance, performanceError, refreshPerformance, markers, markerError, refreshMarkers };
}
