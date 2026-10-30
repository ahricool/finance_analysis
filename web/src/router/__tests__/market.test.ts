import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it } from 'vitest';
import router from '../index';
import { useAuthStore } from '@/stores/authStore';
import { useMarketStore } from '@/stores/marketStore';

beforeEach(() => {
  localStorage.clear(); setActivePinia(createPinia());
  const auth = useAuthStore(); auth.isLoading = false; auth.loggedIn = true;
  auth.currentUser = { uid: 1, username: 'Tester', email: 'test@example.test', role: 'admin', avatarUrl: null };
});
describe('market navigation', () => {
  it('shares explicit links across pages, unrelated routes and legacy redirects', async () => {
    await router.push('/research/quant?market=US');
    expect(useMarketStore().market).toBe('US');
    await router.push('/market/watch-list');
    expect(useMarketStore().market).toBe('US');
    await router.push('/research/industry-strength');
    expect(useMarketStore().market).toBe('US');
    await router.push('/profile/info');
    await router.push('/market/trend-following');
    expect(router.currentRoute.value.path).toBe('/research/trend-following');
    expect(useMarketStore().market).toBe('US');
    await router.push('/market/holdings?market=CN');
    expect(useMarketStore().market).toBe('CN');
    await router.push('/research/quant/signals');
    expect(useMarketStore().market).toBe('CN');
  });
  it('normalizes invalid markets with the saved preference and preserves other query/hash values', async () => {
    useMarketStore().setMarket('US');
    await router.push('/timeline?market=HK&keep=yes#events');
    expect(router.currentRoute.value.query).toEqual({ market: 'US', keep: 'yes' });
    expect(router.currentRoute.value.hash).toBe('#events');
  });
  it('only enables routes that consume a selectable market, including nested quant views', () => {
    for (const path of ['/timeline', '/market/watch-list', '/market/holdings', '/market/heatmap', '/strategies',
      '/research/quant/models/123', '/research/etf-rotation', '/research/trend-following', '/research/confluence',
      '/research/intraday-confirmation', '/research/signal-center']) {
      expect(router.resolve(path).meta.marketScope).toBe('selectable');
    }
    for (const path of ['/dashboard', '/profile/info', '/tasks/runs', '/notifications', '/crypto/btc', '/missing']) {
      expect(router.resolve(path).meta.marketScope).toBeUndefined();
    }
    expect(router.resolve('/research/options-intelligence').meta.marketScope).toBe('US');
    expect(router.resolve('/research/industry-strength').meta.marketScope).toBe('CN');
  });
});
