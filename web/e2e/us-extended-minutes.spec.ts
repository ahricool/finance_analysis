import { expect, test } from '@playwright/test';

test('US minute chart draws the four trading sessions in the 24-hour window', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.clock.setFixedTime(new Date('2026-11-25T09:06:00Z'));
  // Instrument only the four session-band colors; the chart must actually draw each one.
  await page.addInitScript(() => {
    const original = CanvasRenderingContext2D.prototype.roundRect;
    const colors: Record<string, string> = { '#d97706': 'pre', '#64748b': 'regular', '#0284c7': 'post', '#8b5cf6': 'overnight' };
    CanvasRenderingContext2D.prototype.roundRect = function (x, y, w, h, radii) {
      if (typeof this.fillStyle === 'string' && colors[this.fillStyle] && h <= 6 && w > 1) {
        this.canvas.dataset[`session${colors[this.fillStyle]}`] = 'true';
      }
      original.call(this, x, y, w, h, radii);
    };
  });
  const segments = [
    ['2026-11-24T14:30:00Z', 'regular'], ['2026-11-24T21:00:00Z', 'post'],
    ['2026-11-25T05:00:00Z', 'overnight'], ['2026-11-25T09:00:00Z', 'pre'],
  ];
  const bars = segments.flatMap(([start, session]) => Array.from({ length: 6 }, (_, i) => ({
    timestamp: Date.parse(start!) + i * 60_000, trade_session: session, open: 100 + i, high: 102 + i,
    low: 99 + i, close: 101 + i, volume: 1000, turnover: 100000, confirmed: true,
    sampled: false, sample_count: 0, partial: false, source: 'longbridge',
  })));
  const quote = { symbol: 'AAPL.US', code: 'AAPL.US', market_type: 'US', available: true,
    last_price: 106, pre_close: 103, market_open: false, trade_session: 'Pre', source: 'longbridge',
    event_time: '2026-11-25T09:06:00Z', received_at: '2026-11-25T09:06:00Z' };
  await page.routeWebSocket('**/api/v1/market-data/ws*', socket => socket.send(JSON.stringify({ type: 'quotes', quotes: [quote] })));
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/auth/status') return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
    if (url.pathname === '/api/v1/watch-list/tags') return route.fulfill({ json: [] });
    if (url.pathname === '/api/v1/watch-list') return route.fulfill({ json: { total: 1, items: [{ id: 1, code: 'AAPL.US', name: 'Apple', market_type: 'US', notes: '', tags: [], is_favorite: false }] } });
    if (url.pathname.includes('/market-data/intraday/')) return route.fulfill({ json: { symbol: 'AAPL.US', market: 'US', trading_date: '2026-11-24', generated_at: '2026-11-25T09:06:00Z', reset: !url.searchParams.has('since'), full_snapshot: true, items: bars, quote, events: [] } });
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto('/market/watch-list?market=US');
  const row = page.locator('tbody tr[tabindex="0"]');
  await expect(row).toContainText('Apple');
  await row.locator('td').nth(3).click();
  const panel = page.getByTestId('intraday-panel');
  await expect(panel).toContainText('最近24小时');
  const legend = panel.getByLabel('交易时段图例');
  for (const text of ['盘前', '盘中', '盘后', '夜盘']) await expect(legend).toContainText(text);
  await expect(panel.getByRole('img', { name: /1m K线/ })).toBeVisible();
  await panel.getByRole('button', { name: '查看完整24小时' }).click();
  for (const session of ['pre', 'regular', 'post', 'overnight']) await expect(panel.locator(`canvas[data-session${session}]`).first()).toBeAttached();
});
