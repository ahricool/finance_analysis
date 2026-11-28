import { expect, test } from '@playwright/test';
import { dashboardResponse } from '../tests/fixtures/dashboard';

test('expand all fetches only nearby contracts and switches every expanded row together', async ({ page }) => {
  const rows = Array.from({ length: 60 }, (_, i) => ({
    symbol: `C${i}USDT`, category: 'COIN', underlying_symbol: `C${i}.CRYPTO`, quote: null,
  }));
  const requests = new Set<string>();
  await page.routeWebSocket('**/api/v1/crypto/contracts/ws**', socket => {
    socket.send(JSON.stringify({ items: rows, symbol: null, minutes: null, daily_current: null }));
  });
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/crypto/contracts')) return route.fulfill({ json: { items: rows, symbol: null } });
    if (url.pathname.endsWith('/depth')) return route.fulfill({ contentType: 'application/json', body: 'null' });
    if (url.pathname.endsWith('/bars')) {
      requests.add(url.pathname.split('/').at(-2) + '/' + url.searchParams.get('interval'));
      return route.fulfill({ json: [] });
    }
    return route.fulfill({ json: dashboardResponse(url) });
  });
  await page.goto('/crypto/contracts');
  const toolbar = page.getByRole('toolbar', { name: '表格 K 线' });
  const dataRows = page.getByTestId('contract-row');
  await expect(dataRows).toHaveCount(rows.length);
  expect(requests.size).toBe(0);
  await toolbar.getByRole('button', { name: '全部展开' }).click();
  await expect(page.getByTestId('instrument-chart-row')).toHaveCount(rows.length);
  await expect.poll(() => requests.has('C0USDT/1m')).toBe(true);
  expect(requests.size).toBeLessThan(10);
  expect(requests.has('C59USDT/1m')).toBe(false);
  await page.getByTestId('instrument-chart-row').last().scrollIntoViewIfNeeded();
  await expect.poll(() => requests.has('C59USDT/1m')).toBe(true);
  expect(requests.has('C30USDT/1m')).toBe(false);
  await toolbar.getByRole('button', { name: '日', exact: true }).click();
  await expect.poll(() => requests.has('C0USDT/1d')).toBe(true);
  await page.getByTestId('instrument-chart-row').last().scrollIntoViewIfNeeded();
  await expect.poll(() => requests.has('C59USDT/1d')).toBe(true);
  await toolbar.getByRole('button', { name: '15min', exact: true }).click();
  await expect(page.getByTestId('instrument-chart-row').first().getByText(/周期内 K 线不足/)).toBeVisible();
  await dataRows.first().getByRole('button', { name: 'C0USDT 标的详情' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dataRows.first()).toHaveAttribute('aria-expanded', 'true');
  await toolbar.getByRole('button', { name: '全部收起' }).click();
  await expect(page.getByTestId('instrument-chart-row')).toHaveCount(0);
});
