import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it } from 'vitest';
import { useAuthStore } from '@/stores/authStore';
import router from '../index';

describe('legacy URL redirects', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    const auth = useAuthStore();
    auth.isLoading = false;
    auth.loggedIn = true;
  });

  it.each([
    ['/chat', '/analysis'],
    ['/market/quant', '/research/quant'],
    ['/market/quant/signals', '/research/quant/signals'],
    ['/market/quant/signals/NVDA.US', '/research/quant/signals/NVDA.US'],
    ['/market/quant/datasets', '/research/quant/datasets'],
    ['/market/quant/models', '/research/quant/models'],
    ['/market/quant/models/42', '/research/quant/models/42'],
    ['/market/quant/portfolios', '/research/quant/portfolios'],
    ['/market/etf-rotation', '/research/etf-rotation'],
    ['/market/trend-following', '/research/trend-following'],
    ['/market/crypto/btc', '/research/crypto/btc'],
  ])('redirects %s to %s', async (from, expected) => {
    await router.push(from);
    expect(router.currentRoute.value.path).toBe(expected);
  });

  it('keeps quant market query when redirecting legacy research URLs', async () => {
    await router.push('/market/quant/models?market=US');
    expect(router.currentRoute.value.path).toBe('/research/quant/models');
    expect(router.currentRoute.value.query.market).toBe('US');
    expect(router.currentRoute.value.fullPath).toBe('/research/quant/models?market=US');
  });

  it('keeps dynamic params and extra query when redirecting signal detail', async () => {
    await router.push('/market/quant/signals/AAPL.US?market=CN&tab=history');
    expect(router.currentRoute.value.path).toBe('/research/quant/signals/AAPL.US');
    expect(router.currentRoute.value.params.code).toBe('AAPL.US');
    expect(router.currentRoute.value.query).toEqual({ market: 'CN', tab: 'history' });
  });

  it('inherits market query across research quant pages', async () => {
    await router.push('/research/quant/signals?market=US');
    await router.push('/research/quant/models');
    expect(router.currentRoute.value.path).toBe('/research/quant/models');
    expect(router.currentRoute.value.query.market).toBe('US');
  });
});
