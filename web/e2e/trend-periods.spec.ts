import { expect, test } from '@playwright/test';

for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  test(`strategy periods scope ranking and detail at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(theme => localStorage.setItem('theme', theme), width % 3 === 0 ? 'dark' : 'light');
    const requested: Array<{ path: string; period: string | null }> = [];
    await page.route('**/api/v1/**', async route => {
      const url = new URL(route.request().url());
      const path = url.pathname;
      const period = Number(url.searchParams.get('trend_period') ?? 20);
      requested.push({ path, period: url.searchParams.get('trend_period') });
      if (path.endsWith('/preview') || path.endsWith('/preview/status')) {
        return route.fulfill({ status: 404, json: {} });
      }
      const snapshot = {
        market: 'CN', trade_date: '2026-10-12', code: '000001.SZ', name: `周期${period}`, trend_period: period,
        rank: 1, alpha_score: period, trend_score: 80, rs_score: 70, breakout_score: 75,
        state: 'TRENDING', setup: 'BREAKOUT_LONG', trend_duration_days: 10, features: {
          trend_period: period, ma10: 100, ma20: 98, rsi14: 40, raw_weighted_slope: .01, weighted_r2: .9,
          weighted_slope_percentile: 99, return_5d: .03, return_10d: .05, return_20d: .1,
        }, score_breakdown: {}, reference_price: 101, atr: 2, reasons: [], generated_at: '2026-10-12T12:00:00Z',
      };
      const summary = {
        market: 'CN', trade_date: '2026-10-12', trend_period: period, universe_key: 'cn_trend', benchmark_code: '510300.SH',
        market_regime: 'RISK_ON', market_score: 80, universe_size: 1, rankable_count: 1, candidate_count: 1,
        data_ready_count: 1, data_coverage: 1, generated_at: '2026-10-12T12:00:00Z', warnings: [], features: {}, score_breakdown: {},
      };
      let body: object = { items: [] };
      if (path === '/api/v1/auth/status') body = { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } };
      else if (path.endsWith('/trend-following/dates')) body = { items: ['2026-10-12'] };
      else if (path.endsWith('/trend-following/ranking')) body = { ...summary, items: [snapshot], changes: null, candidates: [] };
      else if (path.endsWith('/trend-following/000001.SZ')) body = { market: 'CN', latest: snapshot, metadata: snapshot, history: [snapshot], market_context: summary };
      else if (path.endsWith('/breadth-history')) body = { market: 'CN', points: [], dates: [], warnings: [] };
      else if (path.endsWith('/transitions')) body = { market: 'CN', items: [], warnings: [] };
      else if (path.includes('/event-study/')) body = { groups: [], events: [], snapshot_dates: [], warnings: [], event_count: 0 };
      return route.fulfill({ json: body });
    });
    await page.goto('/research/trend-following');
    await expect(page.getByTestId('trend-row')).toContainText('周期20');
    const periods = page.getByTestId('trend-period');
    const layout = await periods.evaluate(element => {
      const toolbar = element.parentElement!;
      const style = getComputedStyle(toolbar);
      return {
        flexWrap: getComputedStyle(element).flexWrap,
        right: element.getBoundingClientRect().right,
        toolbarRight: toolbar.getBoundingClientRect().right - parseFloat(style.paddingRight) - parseFloat(style.borderRightWidth),
        buttonTops: Array.from(element.querySelectorAll('button'), button => button.getBoundingClientRect().top),
      };
    });
    expect(layout.flexWrap).toBe('nowrap');
    expect(Math.abs(layout.right - layout.toolbarRight)).toBeLessThanOrEqual(1);
    expect(new Set(layout.buttonTops).size).toBe(1);
    await expect(page.getByTestId('trend-refresh')).toBeVisible();
    await expect(page.getByTestId('trend-run-latest')).toBeVisible();
    for (const period of [40, 60]) {
      await page.getByTestId('trend-period').getByRole('button', { name: `${period}日`, exact: true }).click();
      await expect(page.getByTestId('trend-row')).toContainText(`周期${period}`);
      await expect(page.getByTestId('trend-period').getByRole('button', { name: `${period}日`, exact: true })).toHaveAttribute('aria-pressed', 'true');
      await expect(page.getByTestId('trend-section')).toContainText(`MA${period}`);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`trend-period-${width}.png`), fullPage: false });
    await page.getByTestId('trend-row').click();
    await expect(page.getByTestId('trend-detail')).toContainText('MA30 / MA60');
    expect(requested.some(r => r.path.endsWith('/trend-following/000001.SZ') && r.period === '60')).toBe(true);
    expect(requested.filter(r => r.path.endsWith('/trend-following/ranking')).map(r => r.period)).toEqual(['20', '40', '60']);
  });
}
