import { defineStore } from 'pinia';
import { ref } from 'vue';

export type AppMarket = 'CN' | 'US';
export function isAppMarket(value: unknown): value is AppMarket {
  return value === 'CN' || value === 'US';
}

const STORAGE_KEY = 'selected_market';
function readMarket(): AppMarket {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return isAppMarket(value) ? value : 'CN';
  } catch { return 'CN'; }
}

export const useMarketStore = defineStore('market', () => {
  const market = ref<AppMarket>(readMarket());
  function setMarket(value: AppMarket) {
    market.value = value;
    try { localStorage.setItem(STORAGE_KEY, value); } catch { /* Storage may be unavailable. */ }
  }
  return { market, setMarket };
});
