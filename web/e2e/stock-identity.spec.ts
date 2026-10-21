import { expect, test } from '@playwright/test';
import raw from './fixtures/confluence';
import { dashboardResponse } from '../tests/fixtures/dashboard';

for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`stock identity and research row ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      const errors: string[] = [];
      let researchRequests = 0;
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        const path = url.pathname;
        if (path.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
        if (path.endsWith('/classification')) return route.fulfill({ json: { code: '600001.SH', market: 'CN', memberships: { indices: [], industries: [] } } });
        if (path.endsWith('/quote')) return route.fulfill({ json: { stock_code: '600001.SH', current_price: 12.5, change_percent: 2.1 } });
        if (path.includes('/daily-bars/')) return route.fulfill({ json: { symbol: '600001.SH', market: 'CN', interval: '1d', adjustment: 'forward', items: Array.from({ length: 70 }, (_, index) => ({ trade_date: new Date(Date.UTC(2026, 5, 1 + index)).toISOString().slice(0, 10), open: 10 + index * .1, high: 10.5 + index * .1, low: 9.8 + index * .1, close: 10.3 + index * .1, volume: 10000 + index * 100, amount: null })) } });
        if (path.endsWith('/dates')) return route.fulfill({ json: ['2026-09-22'] });
        if (path.endsWith('/confluence/ranking')) return route.fulfill({ json: raw });
        if (path.startsWith('/api/v1/confluence/')) { researchRequests++; return route.fulfill({ json: { market: raw.market, trade_date: raw.trade_date, algorithm_version: raw.algorithm_version, item: raw.items[0] } }); }
        return route.fulfill({ json: {} });
      });
      await page.goto('/research/confluence');
      const row = page.locator('tbody tr').first();
      const identity = row.getByRole('button', { name: '600001.SH - 测试股票', exact: true });
      await expect(identity.locator('strong')).toHaveCSS('font-weight', '700');
      await identity.locator('.font-mono').click();
      const dialog = page.getByRole('dialog');
      await expect(dialog.getByRole('tab').first()).toHaveText('行情');
      await expect(dialog.getByRole('tab', { name: '行情', exact: true })).toHaveAttribute('data-state', 'active');
      await expect(dialog.getByTestId('daily-kline-card').locator('canvas').first()).toBeVisible();
      expect(researchRequests).toBe(0);
      const box = await dialog.boundingBox();
      expect(box!.width).toBeLessThanOrEqual(width);
      expect(box!.height).toBeLessThanOrEqual(968);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      if (width === 390 || width === 1280) await page.screenshot({ path: testInfo.outputPath(`stock-market-${width}-${theme}.png`) });
      await page.keyboard.press('Escape');
      await expect(dialog).toHaveCount(0);
      await row.locator('td').nth(1).click();
      await expect(dialog.getByRole('tab', { name: '共振', exact: true })).toHaveAttribute('data-state', 'active');
      await expect(dialog).toContainText('Why Confluence');
      await expect(dialog.getByTestId('daily-kline-card')).toHaveCount(0);
      expect(researchRequests).toBe(1);
      await page.keyboard.press('Escape');
      await expect(dialog).toHaveCount(0);
      await identity.locator('strong').click();
      await expect(dialog.getByRole('tab', { name: '行情', exact: true })).toHaveAttribute('data-state', 'active');
      expect(researchRequests).toBe(1);
      expect(errors).toEqual([]);
    });
  }
}

test('dashboard stock identity opens the shared detail and leaves card navigation for its row', async ({ page }) => {
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/classification')) return route.fulfill({ json: { code: '600001.SH', memberships: { indices: [], industries: [] } } });
    if (url.pathname.endsWith('/quote')) return route.fulfill({ status: 404, json: {} });
    if (url.pathname.includes('/daily-bars/')) return route.fulfill({ json: { symbol: '600001.SH', market: 'CN', items: [] } });
    if (url.pathname === '/api/v1/stocks/search') return route.fulfill({ json: { items: [] } });
    if (url.pathname === '/api/v1/quant/signals/ranking') return route.fulfill({ json: { market: url.searchParams.get('market'), trade_date: '2026-09-22', items: [{ code: '600001.SH', name: '测试股票', final_score: 80, trade_date: '2026-09-22' }] } });
    return route.fulfill({ json: dashboardResponse(url) });
  });
  await page.goto('/dashboard');
  await page.getByRole('button', { name: '600001.SH - 测试股票', exact: true }).first().locator('strong').click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('600001.SH');
  await expect(dialog.getByRole('tab', { name: '行情', exact: true })).toHaveAttribute('data-state', 'active');
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await page.getByRole('button', { name: '600001.SH - 测试股票', exact: true }).first().locator('.font-mono').click();
  await expect(dialog).toBeVisible();
  await page.evaluate(() => {
    history.pushState({}, '', '/dashboard?focus=market');
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  await expect(dialog).toHaveCount(0);
});
