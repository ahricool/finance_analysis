import { expect, test } from '@playwright/test';

for (const scope of ['watch-list', 'holdings'] as const) {
  for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
    test(`${scope} inline intraday chart and detail at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1100 });
      await page.clock.setFixedTime(new Date('2026-10-21T02:30:00Z'));
      await page.addInitScript(dark => localStorage.setItem('theme', dark ? 'dark' : 'light'), width % 2 === 0 && width < 1280);
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      const items = [
        { id: 1, code: '600519.SH', name: '贵州茅台', market_type: 'CN', notes: '', tags: [], is_favorite: false },
        { id: 2, code: 'AAPL.US', name: 'Apple', market_type: 'US', notes: '', tags: [], is_favorite: false },
      ];
      const position = { id: 1, account_id: 1, market: 'CN', symbol: '600519.SH', name: '贵州茅台', asset_type: 'STOCK', quantity: '100', average_cost: '100', current_price: '110', market_value: '11000', weight: '0.11', unrealized_pnl: '1000', unrealized_pnl_pct: '10', trade_engine_enabled: true };
      const signal = { timeframe: '1m', pattern_type: 'breakout_retest_continuation', pattern_name: '突破回踩延续', direction: 'bullish_continuation', stage: 'confirmed', quality_score: 83, occurred_at: '2026-10-21T02:15:00Z', confirmed_at: '2026-10-21T02:27:00Z', observed_at: '2026-10-21T02:28:03Z', trading_date: '2026-10-21', bars_ago: 2, session_minutes_ago: 2, reference_level: 109, invalidation_price: 106, reasons: ['突破后回踩守住参考位'], confirmed: true };
      const quote = { code: '600519.SH', symbol: '600519.SH', market_type: 'CN', available: true, source: 'fuyao', last_price: 110, change_pct: 2.5, event_time: '2026-10-21T02:30:00Z', received_at: '2026-10-21T02:30:00Z', market_open: true, session_close: '2026-10-21T07:00:00Z', trend_1m: { timeframe: '1m', state: 'above', target_period: 20, effective_period: 20, minimum_period: 5, streak: 8, bar_time: '2026-10-21T02:29:00Z', confirmed: true }, pattern_1m: { timeframe: '1m', status: 'active', signal } };
      const bars = Array.from({ length: 61 }, (_, index) => ({ timestamp: Date.parse('2026-10-21T01:30:00Z') + index * 60_000, open: 100 + index * 0.15, high: 101 + index * 0.15, low: 99.5 + index * 0.15, close: 100.5 + index * 0.15, volume: 1000 + index * 10, turnover: null, confirmed: index < 60, sampled: true, sample_count: 6, partial: false }));
      await page.routeWebSocket('**/api/v1/market-data/ws*', socket => {
        socket.send(JSON.stringify({ type: 'quotes', generated_at: '2026-10-21T02:30:00Z', quotes: [quote] }));
      });
      let intradayRequests = 0;
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        if (url.pathname === '/api/v1/auth/status') return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
        if (url.pathname === '/api/v1/watch-list/tags') return route.fulfill({ json: [] });
        if (url.pathname === '/api/v1/watch-list') { const rows = items.filter(item => item.market_type === (url.searchParams.get('market') ?? 'CN')); return route.fulfill({ json: { items: rows, total: rows.length } }); }
        if (url.pathname === '/api/v1/holdings/summary') return route.fulfill({ json: { market: 'CN', accounts: [{ id: 1, name: 'A股账户', market: 'CN', cash: '89000', currency: 'CNY' }], cash: '89000', market_value: '11000', total_asset: '100000', gross_exposure: '0.11', positions: [position] } });
        if (url.pathname.includes('/market-data/intraday/')) { intradayRequests++; return route.fulfill({ json: { symbol: '600519.SH', market: 'CN', trading_date: '2026-10-21', generated_at: '2026-10-21T02:30:00Z', reset: !url.searchParams.has('since'), items: bars, quote, events: [signal] } }); }
        if (url.pathname.includes('/daily-bars/')) return route.fulfill({ json: { symbol: '600519.SH', market: 'CN', items: [], interval: '1d', adjustment: 'forward' } });
        if (/\/holdings\/positions\/\d+$/.test(url.pathname)) return route.fulfill({ json: position });
        if (url.pathname.includes('/stocks/600519.SH/info')) return route.fulfill({ json: { stock_code: '600519.SH', stock_name: '贵州茅台' } });
        return route.fulfill({ json: { items: [] } });
      });
      await page.goto(`/market/${scope}`);
      const row = scope === 'holdings' ? page.getByTestId('position-row') : page.locator('tbody tr[tabindex="0"]');
      await expect(row).toContainText('贵州茅台');
      expect(intradayRequests).toBe(0);
      await row.locator('td').nth(3).click();
      const panel = page.getByTestId('intraday-panel');
      await expect(panel).toBeVisible();
      await expect(panel.getByRole('img', { name: /1m K线/ })).toBeVisible();
      await expect(panel).toContainText('多头确认');
      await expect(panel).toContainText('10秒采样近似K线');
      await expect(panel).toContainText('突破回踩延续');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      await page.screenshot({ path: testInfo.outputPath(`${scope}-intraday-${width}.png`), fullPage: true });
      await row.getByRole('button', { name: /贵州茅台/ }).first().click();
      await expect(page.getByRole('dialog', { name: /600519/ })).toBeVisible();
      expect(errors).toEqual([]);
    });
  }
}
