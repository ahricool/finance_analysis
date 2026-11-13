import { expect, test } from '@playwright/test';
import { dashboardResponse } from '../tests/fixtures/dashboard';

for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`prediction events ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(value => { localStorage.setItem('theme', value); localStorage.setItem('selected_market', 'US'); }, theme);
      const errors: string[] = []; let histories = 0;
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        const tag = { tag_id: '1', slug: 'tech', label: 'Technology', visible: true, rule_group: 'technology', manual_visible: null, event_count: 11 };
        if (url.pathname.endsWith('/prediction-markets/tags')) return route.fulfill({ json: { status: 'ready', items: [tag] } });
        if (url.pathname.endsWith('/prediction-markets/events')) return route.fulfill({ json: { status: 'ready', total: 11, page: Number(url.searchParams.get('page')), page_size: 10, items: [{ event_id: url.searchParams.get('page') === '2' ? '2' : '1', title: 'Will a major semiconductor company complete an IPO before the deadline?', description: '', slug: 'example', url: 'https://polymarket.com/event/example', tags: [tag], end_at: '2026-12-31T00:00:00Z', closed: false, retained: true, rule_retained: true, rule_reason: 'selected_tag', manual_retained: null, synced_at: '2026-11-13T00:00:00Z' }] } });
        if (url.pathname.endsWith('/live')) return route.fulfill({ json: { status: 'ready', fetched_at: '2026-11-13T00:00:00Z', stale: false, markets: [{ id: 'm', version: 'v2', question: 'IPO before December?', closed: false, resolved: false, outcomes: Array.from({ length: 5 }, (_, i) => ({ id: String(i), label: `Choice ${i}`, probability: i ? null : 0, price_type: 'gamma_outcome_price' })) }] } });
        if (url.pathname.endsWith('/history')) { histories++; return route.fulfill({ json: { status: 'ready', points: [{ timestamp: 1794528000, price: .2, resolution_seconds: 300 }, { timestamp: 1794614400, price: .3, resolution_seconds: 0 }], series_as_of: 1794614400, fetched_at: '2026-11-13T00:00:00Z', changes: { '24h': { percentage_points: 10, reason: null }, '7d': { percentage_points: null, reason: 'insufficient_history' } } } }); }
        try { return route.fulfill({ json: dashboardResponse(url) }); } catch { return route.fulfill({ json: {} }); }
      });
      await page.goto('/market/prediction-events');
      const card = page.getByTestId('prediction-event-card');
      await expect(card).toContainText('0.0%');
      await expect(card).not.toContainText('匹配');
      expect(histories).toBe(0);
      await expect(page.getByTestId('global-market-switch')).toBeDisabled();
      await card.getByRole('button', { name: /展开全部问题与选项/ }).click();
      await expect(card).toContainText('Choice 4');
      await card.getByRole('button', { name: '变化与趋势' }).first().click();
      await expect(page.getByTestId('prediction-history')).toContainText('10.00 个百分点');
      expect(histories).toBe(1);
      const chart = await page.getByTestId('prediction-history-chart').boundingBox();
      expect(chart?.height).toBeGreaterThan(200);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      expect(await page.evaluate(() => localStorage.getItem('selected_market'))).toBe('US');
      await page.screenshot({ path: testInfo.outputPath(`prediction-${width}-${theme}.png`), fullPage: true });
      await page.getByRole('button', { name: '下一页' }).click();
      await expect(page.getByTestId('prediction-history')).toHaveCount(0);
      expect(errors).toEqual([]);
    });
  }
}
