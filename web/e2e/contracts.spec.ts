import { expect, test } from '@playwright/test';
import { dashboardResponse } from '../tests/fixtures/dashboard';

test('USD-M market lists contract prices, switches native candles and manages symbols without Binance browser traffic', async ({ page }) => {
  const initial = [
    { symbol: 'BTCUSDT', category: '加密货币', underlying_symbol: 'BTC.CRYPTO', quote: { price: 100000, change_pct: 2.1, turnover: 20000000, funding_rate: 0.0001, timestamp: Date.now() } },
    { symbol: 'NVDAUSDT', category: '美股', underlying_symbol: 'NVDA.US', quote: { price: 123, change_pct: 1, turnover: 1000000, funding_rate: 0, timestamp: Date.now() } },
    { symbol: 'SOXLUSDT', category: 'ETF', underlying_symbol: 'SOXL.US', quote: { price: 45.12, change_pct: -1, turnover: 1000000, funding_rate: -0.0002, timestamp: Date.now() } },
  ];
  const candle = (timestamp: number) => ({ timestamp, open: 40, high: 47, low: 39, close: 45, volume: 100, turnover: 4500 });
  const day = Math.floor(Date.now() / 86400000) * 86400000;
  const minute = Math.floor(Date.now() / 60000) * 60000;
  const minutes = Array.from({ length: 60 }, (_, index) => candle(minute - (59 - index) * 60000));
  let rows = [...initial];
  const requests: string[] = [];
  const errors: string[] = [];
  page.on('request', request => requests.push(request.url()));
  page.on('pageerror', error => errors.push(error.message));
  await page.routeWebSocket('**/api/v1/crypto/contracts/ws**', socket => {
    const url = new URL(socket.url());
    socket.send(JSON.stringify({
      items: rows, symbol: url.searchParams.get('symbol'),
      minutes: url.searchParams.get('interval') === '1m' ? minutes : null,
      daily_current: candle(day),
    }));
  });
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.pathname === '/api/v1/auth/status') return route.fulfill({ json: {
      loggedIn: true, user: { uid: 1, username: 'Tester', email: 'test@example.com', role: 'admin' },
    } });
    if (url.pathname === '/api/v1/stocks/NVDA.US/quote') return route.fulfill({ json: { stock_code: 'NVDA.US', current_price: 456 } });
    if (url.pathname === '/api/v1/stocks/NVDA.US/classification') return route.fulfill({ json: { memberships: { industries: [], indices: [] }, etf_proxies: [] } });
    if (url.pathname === '/api/v1/market-data/daily-bars/NVDA.US') return route.fulfill({ json: { symbol: 'NVDA.US', market: 'US', items: [] } });
    if (url.pathname === '/api/v1/crypto/contracts/search') return route.fulfill({ json: [{ symbol: 'ETHUSDT', category: 'COIN', underlying_symbol: 'ETH.CRYPTO' }] });
    if (url.pathname.endsWith('/bars')) return route.fulfill({ json: Array.from({ length: 30 }, (_, index) => candle(day - (30 - index) * 86400000)) });
    if (method === 'POST' && url.pathname === '/api/v1/crypto/contracts') {
      const saved = { ...route.request().postDataJSON(), underlying_symbol: 'ETH.CRYPTO' };
      rows.push({ ...saved, quote: null });
      return route.fulfill({ status: 201, json: saved });
    }
    if (method === 'DELETE' && url.pathname.endsWith('/ETHUSDT')) {
      rows = rows.filter(row => row.symbol !== 'ETHUSDT');
      return route.fulfill({ status: 204 });
    }
    if (url.pathname === '/api/v1/crypto/contracts') return route.fulfill({ json: { items: rows, symbol: null, minutes: null, daily_current: null } });
    return route.fulfill({ json: dashboardResponse(url) });
  });
  await page.goto('/crypto/contracts');
  await expect(page.getByTestId('contracts-page')).toBeVisible();
  await expect(page.getByRole('button', { name: 'BTCUSDT 标的详情', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'BTCUSDT 标的详情' }).click();
  await expect(page.getByRole('dialog')).toContainText('BTC');
  await expect(page.getByTestId('underlying-empty')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'NVDAUSDT 标的详情' }).click();
  await expect(page.getByRole('dialog')).toContainText('NVDA.US');
  await expect(page.getByRole('dialog')).toContainText('456');
  await expect(page.getByRole('dialog')).not.toContainText('123');
  await expect(page.getByRole('tab', { name: '趋势', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('row').filter({ hasText: 'SOXLUSDT' })).toContainText('-0.0200%');
  await page.getByRole('button', { name: '查看 SOXLUSDT 合约 K 线', exact: true }).click();
  await expect(page.getByRole('img', { name: /SOXLUSDT 1d K线/ })).toBeVisible();
  await page.getByRole('button', { name: '1 分钟 K' }).click();
  await expect(page.getByRole('img', { name: /SOXLUSDT 1m K线/ })).toBeVisible();
  await page.getByRole('textbox', { name: '搜索合约' }).fill('ETH');
  await page.getByRole('button', { name: '搜索', exact: true }).click();
  await page.getByRole('button', { name: 'ETHUSDT · 添加' }).click();
  await expect(page.getByRole('button', { name: 'ETHUSDT 标的详情', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '移除 ETHUSDT' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: '确定' }).click();
  await expect(page.getByRole('button', { name: 'ETHUSDT 标的详情', exact: true })).toHaveCount(0);
  for (const width of [390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  expect(errors).toEqual([]);
  expect(requests.some(url => url.includes('/stocks/BTC') || url.includes('/daily-bars/BTC') || url.includes('BTC.CRYPTO'))).toBe(false);
  expect(requests.some(url => /binance\.(com|vision)/.test(url))).toBe(false);
  expect(requests.some(url => url.includes('/minute-forecast/'))).toBe(false);
});
