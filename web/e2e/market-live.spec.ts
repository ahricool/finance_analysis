import { expect, test } from '@playwright/test';
import { dashboardResponse } from '../tests/fixtures/dashboard';

const portfolio = {
  market: 'CN', accounts: [{ id: 1, name: 'A股账户', market: 'CN', cash: '90000', currency: 'CNY' }],
  cash: '90000', market_value: '12000', total_asset: '102000', gross_exposure: '0.1176', missing_quote_count: 0,
  generated_at: '2026-10-14T02:41:10Z',
  positions: [{ id: 11, account_id: 1, market: 'CN', symbol: '600519.SH', name: '贵州茅台', asset_type: 'STOCK',
    quantity: '100', average_cost: '100', current_price: '120', market_value: '12000', weight: '0.1176',
    unrealized_pnl: '2000', unrealized_pnl_pct: '20', change_pct: '2.5', change_amount: '3', day_pnl: '300',
    quote_time: '2026-10-14T02:41:09Z', quote_source: 'fuyao', quote_status: 'current', trade_engine_enabled: true }],
};

for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  test(`holdings live fallback, metrics and layout at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    let wsRequests = 0;
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.routeWebSocket('**/api/v1/market-data/ws*', socket => {
      wsRequests++;
      socket.close({ code: 1011, reason: 'test WS unavailable' });
    });
    await page.route('**/api/v1/**', route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/v1/holdings/summary') return route.fulfill({ json: portfolio });
      if (url.pathname === '/api/v1/trade-engine/positions') return route.fulfill({ json: { items: [] } });
      if (url.pathname === '/api/v1/market-data/events') return route.fulfill({
        contentType: 'text/event-stream',
        body: `data: ${JSON.stringify({ type: 'quotes', generated_at: portfolio.generated_at, quotes: [], portfolio })}\n\n`,
      });
      return route.fulfill({ json: dashboardResponse(url) });
    });
    await page.goto('/market/holdings');
    const row = page.getByTestId('position-row');
    await expect(row).toContainText('贵州茅台');
    await expect(row).toContainText('+20.00%');
    await expect(row).toContainText('+2,000.00');
    await expect(row).toContainText('+300.00');
    await expect(page.getByRole('columnheader', { name: '当日涨跌' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: '市值', exact: true })).toHaveCount(0);
    await expect.poll(() => wsRequests).toBe(2);
    await expect.poll(() => page.locator('body').textContent()).toContain('SSE');
    await page.getByRole('columnheader', { name: '当日涨跌' }).getByRole('button', { name: '当日涨跌', exact: true }).click();
    await expect(page.getByRole('columnheader', { name: '当日涨跌' })).toHaveAttribute('aria-sort', 'descending');
    await page.getByRole('columnheader', { name: '当日涨跌' }).getByRole('button', { name: '当日涨跌', exact: true }).click();
    await expect(page.getByRole('columnheader', { name: '当日涨跌' })).toHaveAttribute('aria-sort', 'ascending');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`holdings-live-${width}.png`), fullPage: true });
    expect(errors).toEqual([]);
    expect(wsRequests).toBe(2);
  });
}
