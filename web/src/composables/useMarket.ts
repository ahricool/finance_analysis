import { computed, inject } from 'vue';
import { routeLocationKey } from 'vue-router';
import { isAppMarket, useMarketStore } from '@/stores/marketStore';

/** The active URL can select a market; the saved preference carries it across pages. */
export function useMarket() {
  const store = useMarketStore();
  const route = inject(routeLocationKey, undefined);
  const market = computed(() => isAppMarket(route?.query.market) ? route.query.market : store.market);
  return { market };
}
