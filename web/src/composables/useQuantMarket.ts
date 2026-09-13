import type { QuantMarket } from '@/types/quant';
import { parseDate } from '@internationalized/date';
import { computed } from 'vue';
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router';

export function normalizeQuantMarket(value: unknown): QuantMarket {
  return value === 'CN' ? 'CN' : 'US';
}

export function useQuantMarket() {
  const route = useRoute();
  const router = useRouter();
  const market = computed<QuantMarket>(() => normalizeQuantMarket(route.query.market));
  const tradeDate = computed(() => {
    const value = route.query.tradeDate;
    if (typeof value !== 'string') return '';
    try {
      return parseDate(value).toString();
    } catch {
      return '';
    }
  });

  async function setTradeDate(value: string): Promise<void> {
    const query = { ...route.query };
    if (value) query.tradeDate = value;
    else delete query.tradeDate;
    await router.push({ path: route.path, query });
  }

  async function setMarket(value: QuantMarket): Promise<void> {
    if (value === market.value && route.query.market === value) return;
    await router.push({ path: route.path, query: { ...route.query, market: value } });
  }

  function marketQuery(extra: LocationQueryRaw = {}): LocationQueryRaw {
    return { ...route.query, ...extra, market: market.value };
  }

  return { market, setMarket, marketQuery, tradeDate, setTradeDate };
}
