import { createPinia, setActivePinia } from 'pinia';
import { describe, expect, it } from 'vitest';
import { useAuthStore } from '@/stores/authStore';
import router, { resolveDocumentTitle } from '../index';

describe('router document titles', () => {
  it.each([
    ['/', 'Finance Analysis'],
    ['/dashboard', '市场动态 - Finance Analysis'],
    ['/analysis', '分析 - Finance Analysis'],
    ['/timeline', '投资时间线 - Finance Analysis'],
    ['/market/watch-list', '自选股 - Finance Analysis'],
    ['/market/holdings', '投资组合 - Finance Analysis'],
    ['/research/quant', '量化研究 - Finance Analysis'],
    ['/research/quant/signals', '模型选股 - Finance Analysis'],
    ['/research/quant/signals/NVDA.US', '选股详情 - Finance Analysis'],
    ['/research/quant/models', '量化模型 - Finance Analysis'],
    ['/research/quant/portfolios', '目标组合 - Finance Analysis'],
    ['/research/etf-rotation', 'ETF动量轮动 - Finance Analysis'],
    ['/research/trend-following', '趋势跟踪 - Finance Analysis'],
    ['/research/crypto/btc', 'BTC交易 - Finance Analysis'],
    ['/profile', '个人中心 - Finance Analysis'],
    ['/profile/info', '个人中心 - Finance Analysis'],
    ['/profile/password', '个人中心 - Finance Analysis'],
    ['/profile/notification', '个人中心 - Finance Analysis'],
    ['/tasks', '任务中心 - Finance Analysis'],
    ['/tasks/scheduled', '任务中心 - Finance Analysis'],
    ['/tasks/runs', '任务中心 - Finance Analysis'],
    ['/login', '登录 - Finance Analysis'],
    ['/missing-page', '页面未找到 - Finance Analysis'],
  ])('resolves %s to %s', (path, expectedTitle) => {
    expect(resolveDocumentTitle({ matched: router.resolve(path).matched })).toBe(expectedTitle);
  });

  it('does not register the removed top-level stock routes', () => {
    expect(router.hasRoute('watch-list')).toBe(false);
    expect(router.hasRoute('stock-list')).toBe(false);
    expect(router.resolve('/watch-list').name).toBe('not-found');
    expect(router.resolve('/stock-list').name).toBe('not-found');
  });

  it('does not keep former chat or market-research route names', () => {
    expect(router.hasRoute('chat')).toBe(false);
    expect(router.hasRoute('market-quant')).toBe(false);
    expect(router.hasRoute('market-etf-rotation')).toBe(false);
    expect(router.hasRoute('market-trend-following')).toBe(false);
    expect(router.hasRoute('market-crypto-btc')).toBe(false);
    expect(router.hasRoute('research-quant')).toBe(true);
    expect(router.hasRoute('research-etf-rotation')).toBe(true);
    expect(router.resolve('/analysis').name).toBe('analysis');
  });

  it('redirects the root path to the dashboard', () => {
    expect(router.resolve('/').matched.at(-1)?.redirect).toEqual({ name: 'dashboard' });
    expect(router.resolve('/analysis').name).toBe('analysis');
  });

  it('redirects profile to info and registers every route-driven profile tab', async () => {
    setActivePinia(createPinia());
    const auth = useAuthStore();
    auth.isLoading = false;
    auth.loggedIn = true;

    expect(router.resolve('/profile/info').name).toBe('profile-info');
    expect(router.resolve('/profile/password').name).toBe('profile-password');
    expect(router.resolve('/profile/notification').name).toBe('profile-notification');

    await router.push('/profile');

    expect(router.currentRoute.value.path).toBe('/profile/info');
    expect(router.currentRoute.value.name).toBe('profile-info');
  });
});

it('defaults an authenticated login route to dashboard', async () => {
  setActivePinia(createPinia());
  const auth = useAuthStore();
  auth.isLoading = false;
  auth.loggedIn = true;
  await router.push('/login');
  expect(router.currentRoute.value.path).toBe('/dashboard');
});
