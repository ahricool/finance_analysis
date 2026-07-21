import type { QuantMarket } from '@/types/quant';
import { computed } from 'vue';
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router';

export function normalizeQuantMarket(value: unknown): QuantMarket {
  return value === 'CN' ? 'CN' : 'US';
}

export function useQuantMarket() {
  const route = useRoute();
  const router = useRouter();
  const market = computed<QuantMarket>(() => normalizeQuantMarket(route.query.market));

  async function setMarket(value: QuantMarket): Promise<void> {
    if (value === market.value && route.query.market === value) return;
    await router.push({ path: route.path, query: { ...route.query, market: value } });
  }

  function marketQuery(extra: LocationQueryRaw = {}): LocationQueryRaw {
    return { ...route.query, ...extra, market: market.value };
  }

  return { market, setMarket, marketQuery };
}
