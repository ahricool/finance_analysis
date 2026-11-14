import { expect, test } from '@playwright/test';
import { dashboardResponse } from '../tests/fixtures/dashboard';

for (const width of [390, 1280]) {
  for (const theme of ['light', 'dark']) {
    test(`stock Polymarket lazy search at ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      const errors: string[] = [];
      let searches = 0, histories = 0;
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
            unrealized_pnl: '2000' }],
        } });
        if (path.includes('/prediction-markets/stocks/')) {
          searches++;
          return route.fulfill({ json: { status: 'ready', queries: ['贵州茅台', '600519'], items: Array.from({ length: 20 }, (_, i) => ({ event_id: String(i+1), title: `Company event ${i+1}`, url: 'https://polymarket.com/event/test', closed: false, volume_24h: i, end_at: null })), fetched_at: '2026-11-14T00:00:00Z' } });
        }
        if (path.endsWith('/live')) return route.fulfill({ json: { status: 'ready', markets: [{ id: '1', question: 'Question?', version: 'v2', outcomes: [{ id: '10', label: 'No', probability: 0 }, { id: '11', label: 'Yes', probability: 1 }] }] } });
        if (path.endsWith('/history')) { histories++; return route.fulfill({ json: { status: 'ready', points: [] } }); }
        if (path.endsWith('/quote')) return route.fulfill({ status: 404, json: { detail: 'No quote' } });
        if (path.endsWith('/classification')) {

          return route.fulfill({ json: { code: '600519.SH', market: 'CN', etf_proxies: [
            { code: '159928.SZ', name: '消费ETF', reasons: ['食品饮料：消费行业宽口径代理'] },
            { code: '512690.SH', name: '酒ETF', reasons: ['白酒：酒类行业代理'] },
          ], etf_proxy_unavailable_reasons: [], memberships: { indices: [], industries: [
            { code: '881101.TI', name: '食品饮料', members_observed_at: '2026-10-11T02:00:00Z' },
            { code: '881102.TI', name: '白酒', members_observed_at: '2026-10-11T02:00:00Z' },
          ] } } });
        }
        if (path.endsWith('/operations') || path.endsWith('/markers')) {
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
      await page.getByTestId('position-row').getByRole('button', { name: '600519.SH - 贵州茅台', exact: true }).click();
      const dialog = page.getByRole('dialog');
      expect(searches).toBe(0);
      await dialog.getByRole('tab', { name: 'Polymarket', exact: true }).click();
      await expect(dialog.getByTestId('prediction-event-card')).toHaveCount(20);
      await expect(dialog.getByTestId('prediction-event-card').first()).toContainText('No：0.0%');
      await expect(dialog.getByTestId('prediction-event-card').first()).toContainText('24h 成交额：$0');
      expect(searches).toBe(1); expect(histories).toBe(0);
      if (width === 390 || width === 1280) {
        await page.screenshot({ path: testInfo.outputPath(`polymarket-stock-${width}-${theme}.png`) });
      }
      await dialog.getByRole('tab', { name: '行情', exact: true }).click();
      await expect(dialog.getByTestId('polymarket-detail-panel')).toHaveCount(0);
      const box = await dialog.boundingBox();
      expect(box!.width).toBeLessThanOrEqual(width);
      expect(box!.height).toBeLessThanOrEqual(968);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

      expect(errors).toEqual([]);
    });
  }
}
