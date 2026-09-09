import { onUnmounted, shallowReactive, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { parseDate } from '@internationalized/date';
import { quantApi } from '@/api/quant';
import { timelineApi } from '@/api/timeline';
import { etfRotationApi } from '@/api/etfRotation';
import { trendFollowingApi } from '@/api/trendFollowing';
import { cryptoApi } from '@/api/crypto';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { useTimezoneStore } from '@/stores/timezoneStore';
import { getTodayInDisplayTimezone } from '@/utils/format';

/** Independent public read resources; a failed module never blocks another module. */
export function useMarketDashboard() {
  let stopped = false;
  function resource<T>(fetcher: () => Promise<T>) {
    const state = shallowReactive({ data: null as T | null, loading: true, error: null as ParsedApiError | null });
    let generation = 0;
    async function refresh() {
      const current = ++generation;
      state.loading = state.data === null;
      state.error = null;
      try {
        const data = await fetcher();
        if (!stopped && current === generation) state.data = data;
      } catch (error) {
        if (!stopped && current === generation) state.error = getParsedApiError(error);
      } finally {
        if (!stopped && current === generation) state.loading = false;
      }
    }
    return Object.assign(state, { refresh });
  }
  const markets = (['CN', 'US'] as const).map(market => ({
    market,
    regime: resource(() => quantApi.marketRegime(market)),
    signals: resource(() => quantApi.signals(market)),
    etf: resource(() => etfRotationApi.ranking(market)),
    trend: resource(() => trendFollowingApi.ranking(market)),
  }));
  // No cutoff on Latest: future events participate in the same event_time DESC feed.
  const latest = resource(() => timelineApi.list({ limit: 10 }));
  // Query an upper bound only. The page filters future events without changing API order.
  const upcoming = resource(() => timelineApi.list({
    category: 'event', end_date: parseDate(getTodayInDisplayTimezone()).add({ days: 7 }).toString(), limit: 100,
  }));
  const btc = resource(() => cryptoApi.overview());
  for (const market of markets) {
    for (const section of [market.regime, market.signals, market.etf, market.trend]) void section.refresh();
  }
  void btc.refresh();
  const { displayTimezone } = storeToRefs(useTimezoneStore());
  watch(displayTimezone, () => { void latest.refresh(); void upcoming.refresh(); }, { immediate: true });
  // Use the existing public overview, without duplicating the BTC socket or loading chart history.
  const timer = window.setInterval(() => { void btc.refresh(); }, 30_000);
  onUnmounted(() => { stopped = true; window.clearInterval(timer); });
  return { markets, latest, upcoming, btc };
}
