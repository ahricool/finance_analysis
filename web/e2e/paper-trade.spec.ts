import { expect, test } from '@playwright/test';
import { dashboardResponse } from '../tests/fixtures/dashboard';
import type { PaperSnapshot } from '../src/api/paperTrade';

const empty: PaperSnapshot = {
  connection: { status: 'NOT_CONFIGURED', stream_connected: false }, view: null,
  trade_control: { enabled: false, updated_at: null },
  equity: [], orders: [], algos: [], strategies: [], trades: [], income: [], intents: [], realized_net: null,
};

test('admin Demo page has independent status, explicit order confirmation and no exchange traffic', async ({ page }) => {
  let snapshot: PaperSnapshot = { ...empty };
  const writes: { path: string; payload: unknown }[] = [];
  const errors: string[] = [];
  const requests: string[] = [];
  page.on('pageerror', err => errors.push(err.message));
  page.on('request', request => requests.push(request.url()));
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/auth/status') return route.fulfill({ json: {
      loggedIn: true, user: { uid: 1, username: 'Tester', email: 'test@example.com', role: 'admin' },
    } });
    if (url.pathname === '/api/v1/crypto/paper-trade') return route.fulfill({ json: snapshot });
    if (url.pathname === '/api/v1/crypto/paper-trade/control') {
      if (route.request().method() === 'PUT') snapshot = { ...snapshot, trade_control: {
        enabled: route.request().postDataJSON().enabled, updated_at: new Date().toISOString(),
      } };
      return route.fulfill({ json: snapshot.trade_control });
    }
    if (url.pathname === '/api/v1/crypto/contracts') return route.fulfill({ json: { items: [], symbol: null, minutes: null, daily_current: null } });
    if (url.pathname.startsWith('/api/v1/crypto/paper-trade/') && route.request().method() !== 'GET') {
      writes.push({ path: url.pathname, payload: route.request().postDataJSON() });
      return route.fulfill({ json: { status: 'QUEUED' }, status: 202 });
    }
    return route.fulfill({ json: dashboardResponse(url) });
  });
  await page.goto('/crypto/paper-trade');
  await expect(page.getByTestId('paper-trade-page')).toBeVisible();
  await expect(page.getByTestId('demo-connection')).toContainText('未配置 Demo API');
  await expect(page.getByRole('button', { name: '核对模拟委托' })).toBeDisabled();
  await expect(page.getByTestId('demo-quantity')).toHaveValue('');
  snapshot = { ...empty, connection: { status: 'CONNECTED', stream_connected: true },
    view: { account: { totalMarginBalance: '5000.00', totalWalletBalance: '4999.00', availableBalance: '4800.00' },
      synced_at: new Date().toISOString(), complete: true, demo_symbols: ['BTCUSDT'], shared_symbols: ['BTCUSDT'],
      positions: [{ symbol: 'BTCUSDT', positionSide: 'BOTH', positionAmt: '0.001', source: 'EXTERNAL' }],
      open_orders: [{ symbol: 'BTCUSDT', orderId: '12345678901234567' }],
      open_algos: [{ symbol: 'BTCUSDT', algoId: '456' }] },
    orders: [{ symbol: 'BTCUSDT', orderId: '12345678901234567', status: 'NEW', side: 'BUY', type: 'LIMIT' }],
    algos: [{ symbol: 'BTCUSDT', algoId: '456', algoStatus: 'NEW', side: 'SELL' }],
    trades: [{ symbol: 'BTCUSDT', id: '111', side: 'BUY', source: 'EXTERNAL', qty: '0.001' }],
    strategies: [{ symbol: 'BTCUSDT', name: 'EMA 验证', enabled: false, status: 'PAUSED' }],
  };
  await page.getByRole('button', { name: '刷新' }).click();
  await expect(page.getByTestId('demo-connection')).toContainText('连接正常');
  await expect(page.getByText('5000.00', { exact: true })).toBeVisible();
  await expect(page.getByText('EMA 验证', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('12345678901234567', { exact: true })).toBeVisible();
  const toggle = page.getByTestId('paper-trading-switch');
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  await page.getByRole('button', { name: '启用', exact: true }).click();
  await expect(page.getByRole('alertdialog')).toContainText('关闭页面后仍运行');
  await page.getByRole('alertdialog').getByRole('button', { name: '取消' }).click();
  expect(writes).toHaveLength(0);
  await page.getByRole('button', { name: '撤单', exact: true }).first().click();
  await expect(page.getByRole('alertdialog')).toContainText('12345678901234567');
  await page.getByRole('alertdialog').getByRole('button', { name: '确认提交' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]!.payload).toMatchObject({ exchange_id: '12345678901234567', confirm_demo: true, algo: false });
  await page.getByRole('combobox', { name: 'Demo 合约' }).click();
  await page.getByRole('option', { name: 'BTCUSDT' }).click();
  await page.getByRole('combobox', { name: '方向', exact: true }).click();
  await page.getByRole('option', { name: 'BUY · 买入' }).click();
  await page.getByRole('combobox', { name: '订单类型' }).click();
  await page.getByRole('option', { name: 'MARKET', exact: true }).click();
  await page.getByTestId('demo-quantity').fill('0.001');
  await page.getByRole('button', { name: '核对模拟委托' }).click();
  await expect(page.getByRole('alertdialog')).toContainText('数量 0.001');
  expect(writes).toHaveLength(1);
  await page.getByRole('alertdialog').getByRole('button', { name: '确认提交' }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]!.payload).toMatchObject({ symbol: 'BTCUSDT', side: 'BUY', order_type: 'MARKET', quantity: '0.001', confirm_demo: true });
  await page.getByRole('button', { name: '平仓', exact: true }).click();
  await expect(page.getByRole('alertdialog')).toContainText('仅减仓');
  await page.getByRole('alertdialog').getByRole('button', { name: '取消' }).click();
  expect(writes).toHaveLength(2);
  for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  expect(errors).toEqual([]);
  expect(requests.some(url => /binance\.(com|vision)/.test(url))).toBe(false);
});

test('ordinary user cannot open Demo page', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/auth/status') return route.fulfill({ json: {
      loggedIn: true, user: { uid: 1, username: 'Tester', email: 'test@example.com', role: 'user' },
    } });
    if (url.pathname === '/api/v1/crypto/contracts') return route.fulfill({ json: { items: [], symbol: null, minutes: null, daily_current: null } });
    return route.fulfill({ json: dashboardResponse(url) });
  });
  await page.routeWebSocket('**/api/v1/crypto/contracts/ws**', socket => socket.send(JSON.stringify({ items: [], symbol: null, minutes: null, daily_current: null })));
  await page.goto('/crypto/paper-trade');
  await expect(page).toHaveURL(/\/crypto\/contracts$/);
  await expect(page.getByTestId('contracts-page')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Paper Trade', exact: true })).toHaveCount(0);
});
