import { expect, test } from '@playwright/test';
import { dashboardResponse } from '../tests/fixtures/dashboard';

for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`weekly stock industries at ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      const errors: string[] = [];
      let classifications = 0;
      page.on('pageerror', error => errors.push(error.message));
      await page.routeWebSocket('**/api/v1/market-data/ws*', socket => socket.close({ code: 1011 }));
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        const path = url.pathname;
        if (path === '/api/v1/holdings/summary') return route.fulfill({ json: {
          market: 'CN', accounts: [{ id: 1, name: 'A股账户', market: 'CN', cash: '90000', currency: 'CNY' }],
          cash: '90000', market_value: '12000', total_asset: '102000', gross_exposure: '0.1176',
          positions: [{ id: 11, account_id: 1, market: 'CN', symbol: '600519.SH', name: '贵州茅台', asset_type: 'STOCK',
            quantity: '100', average_cost: '100', current_price: '120', market_value: '12000', weight: '0.1176',
            unrealized_pnl: '2000', trade_engine_enabled: true }],
        } });
        if (path.endsWith('/classification')) {
          classifications++;
          return route.fulfill({ json: { code: '600519.SH', market: 'CN', memberships: { indices: [], industries: [
            { code: '881101.TI', name: '食品饮料', members_observed_at: '2026-10-11T02:00:00Z' },
            { code: '881102.TI', name: '白酒', members_observed_at: '2026-10-11T02:00:00Z' },
          ] } } });
        }
        if (path.startsWith('/api/v1/trade-engine/') || path.endsWith('/operations') || path.endsWith('/markers')) {
          return route.fulfill({ json: { items: [] } });
        }
        if (path.includes('/daily-bars/')) return route.fulfill({ json: { symbol: '600519.SH', bars: [], warnings: [] } });
        if (path.startsWith('/api/v1/industry-strength/stocks/')) return route.fulfill({ json: [] });
        if (path.startsWith('/api/v1/trend-following/') || path.startsWith('/api/v1/etf-rotation/')) {
          return route.fulfill({ json: { latest: null, history: [] } });
        }
        if (path.startsWith('/api/v1/quant/signals/')) return route.fulfill({ status: 404, json: { detail: 'not covered' } });
        if (path === '/api/v1/market-data/events') return route.fulfill({ contentType: 'text/event-stream', body: ': heartbeat\n\n' });
        return route.fulfill({ json: dashboardResponse(url) });
      });
      await page.goto('/market/holdings');
      await page.getByTestId('position-row').getByRole('button', { name: '贵州茅台 600519.SH', exact: true }).click();
      const dialog = page.getByRole('dialog');
      const industries = dialog.getByTestId('stock-industry-tags');
      await expect(industries).toContainText('食品饮料');
      await expect(industries).toContainText('白酒');
      await expect(industries).toContainText('每周同步');
      const box = await dialog.boundingBox();
      expect(box!.width).toBeLessThanOrEqual(width);
      expect(box!.height).toBeLessThanOrEqual(968);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      expect(classifications).toBe(1);
      if (width === 390 || width === 1280) {
        await page.screenshot({ path: testInfo.outputPath(`stock-industry-${width}-${theme}.png`) });
      }
      expect(errors).toEqual([]);
    });
  }
}
