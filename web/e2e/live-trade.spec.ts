import { expect, test } from '@playwright/test';
import type { LiveSnapshot } from '../src/api/liveTrade';
import { dashboardResponse } from '../tests/fixtures/dashboard';

const base = '/api/v1/crypto/live-trade';
const initial: LiveSnapshot = {
  environment: 'LIVE', control: { enabled: false, updated_at: null },
  connection: { status: 'CONNECTED', stream_connected: true },
  view: {
    account: { totalMarginBalance: '1025.50', totalWalletBalance: '1000.00' },
    balances: [{ asset: 'USDT', balance: '1000.00' }],
    positions: [{ symbol: 'BTCUSDT', direction: 'LONG', positionAmt: '0.001', source: 'EXTERNAL' }],
    open_orders: [{ symbol: 'BTCUSDT', orderId: '101', status: 'NEW', source: 'EXTERNAL' }],
    open_algos: [{ symbol: 'BTCUSDT', algoId: '102', algoStatus: 'NEW' }],
    complete: true, synced_at: new Date().toISOString(),
  },
  equity: [{ time: '2026-11-25T01:00:00Z', equity: '1025.50' }], orders: [], algos: [], trades: [{ symbol: 'BTCUSDT', id: '123', side: 'BUY', source: 'EXTERNAL' }],
  income: [], realized_net: '25.50', control_events: [], strategy_count: 0,
};
test('live account switch is persisted locally; no trading UI or Binance browser requests', async ({ page }) => {
  let state = structuredClone(initial);
  let fail = false;
  let selected: string | null = null;
  const mutations: string[] = [];
  const requests: string[] = [];
  page.on('request', request => requests.push(request.url()));
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === '/api/v1/auth/status') return route.fulfill({ json: {
      loggedIn: true, user: { uid: 5, username: 'Admin', email: 'test@example.com', role: 'admin' },
    } });
    if (path === '/api/v1/crypto/strategy') return route.fulfill({ json: {
      items: [{ key: 'ema_cross', name: 'EMA Cross' }], selected: { live: selected, paper: null },
    } });
    if (path === '/api/v1/crypto/strategy/live') {
      selected = route.request().postDataJSON().strategy;
      return route.fulfill({ status: 204 });
    }
    if (path === base) return route.fulfill({ json: state });
    if (path === base + '/control') {
      if (route.request().method() === 'PUT') {
        mutations.push(path);
        if (fail) return route.fulfill({ status: 409, json: { detail: '模拟更新失败' } });
        state = { ...state, control: { enabled: route.request().postDataJSON().enabled, updated_at: new Date().toISOString() } };
      }
      return route.fulfill({ json: state.control });
    }
    return route.fulfill({ json: dashboardResponse(url) });
  });
  await page.goto('/crypto/live-trade');
  await expect(page.getByTestId('live-trade-page')).toBeVisible();
  await expect(page.getByTestId('live-switch-status')).toContainText('自动交易已关闭');
  const controls = page.locator('section').filter({ has: page.getByTestId('live-trading-switch') });
  const strategy = controls.getByRole('combobox', { name: '交易策略' });
  const toggleBox = await controls.getByRole('switch').boundingBox();
  const strategyBox = await strategy.boundingBox();
  expect(strategyBox!.y).toBeGreaterThanOrEqual(toggleBox!.y + toggleBox!.height);
  await strategy.click();
  await page.getByRole('option', { name: 'EMA Cross' }).click();
  await expect.poll(() => selected).toBe('ema_cross');
  const toggle = page.getByRole('switch', { name: '自动交易' });
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  await expect(page.locator('figure canvas')).toBeVisible();
  await expect(page.locator('figcaption')).toContainText('USDT / USD');
  await expect(page.getByText('1025.50', { exact: true })).toBeVisible();
  await expect(page.getByText('Binance · LIVE · 真实账户')).toBeVisible();
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('live-switch-status')).toContainText('交易已启用 · 只读观察');
  await page.reload();
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  fail = true;
  await toggle.click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  expect(mutations).toEqual([base + '/control', base + '/control', base + '/control']);
  for (const label of ['平仓', '撤单', '下单', '买入', '卖出', '设置止损']) {
    await expect(page.getByRole('button', { name: label, exact: true })).toHaveCount(0);
  }
  for (const width of [390, 768, 1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  expect(requests.some(url => /binance\.(com|vision)/.test(url))).toBe(false);
});

test('ordinary user cannot access live account data', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/auth/status') return route.fulfill({ json: {
      loggedIn: true, user: { uid: 5, username: 'User', email: 'test@example.com', role: 'user' },
    } });
    if (url.pathname === '/api/v1/crypto/contracts') return route.fulfill({ json: { items: [], symbol: null, minutes: null, daily_current: null } });
    if (url.pathname.startsWith(base)) throw new Error('Non-admin attempted Live API');
    return route.fulfill({ json: dashboardResponse(url) });
  });
  await page.routeWebSocket('**/api/v1/crypto/contracts/ws**', socket => socket.send(JSON.stringify({ items: [], symbol: null, minutes: null, daily_current: null })));
  await page.goto('/crypto/live-trade');
  await expect(page).toHaveURL(/\/crypto\/contracts$/);
  await expect(page.getByTestId('contracts-page')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Live Trade', exact: true })).toHaveCount(0);
});
