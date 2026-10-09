import { expect, test } from '@playwright/test';
const score = (value: number | null) => ({ value, method: 'initial_absolute_volume_oi_rules', confidence: 'low', evidence_count: 1, reason: value == null ? 'fresh_real_quotes_unavailable' : null });
const metric = { symbol: 'AAPL.US', status: 'warming_up', underlying_price: 220, observed_at: '2026-10-07T21:00:00Z',
  history_days: 0, scores: { bearish_demand: score(null), unusual_activity: score(87), liquidity_risk: score(null) },
  evidence_grade: 'C', limitations: ['quote_timestamp_unknown', 'oi_as_of_unknown'], iv_30d: .31, iv_percentile: null, iv_sample_count: 0,
  skew_30d: null, term_structure: [{ expiration: '2026-11-06', dte: 30, atm_iv: .31, expected_move: 19.55, source: 'yfinance', feed_type: 'delayed', expected_move_method: 'iv_sqrt_act365' }],
  skew_terms: [{ target_dte: 30, actual_dte: null, value: null }],
  contracts: [{ symbol: 'AAPL261106P00220000', expiration: '2026-11-06', option_type: 'put', strike: 220,
    bid: 4, ask: 4.5, volume: 1000, open_interest: 200, oi_date: null, iv: .31, delta: null, spread: .118, volume_oi: 5,
    data_source: 'yfinance', feed_type: 'delayed', quote_status: 'quote_timestamp_unknown', risk: score(null), notes: [] }], events: [],
};
for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`options ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(t => localStorage.setItem('theme', t), theme);
      const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
      await page.route('**/api/v1/**', route => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
        if (path.endsWith('/options-intelligence')) return route.fulfill({ json: { items: [metric] } });
        if (path.endsWith('/options-intelligence/AAPL.US')) return route.fulfill({ json: { symbol: 'AAPL.US', latest: metric, daily_history: [{ ...metric, trade_date: '2026-10-07', skew_30d: 0.1 }], events: [], analyses: [], reason: null } });
        return route.fulfill({ json: {} });
      });
      await page.goto('/research/options-intelligence');
      await expect(page.getByTestId('options-scanner')).toContainText('AAPL.US');
      await page.getByRole('button', { name: 'AAPL.US', exact: true }).click();
      const dialog = page.getByRole('dialog');
      await expect(dialog.getByTestId('options-panel')).toBeVisible();
      await expect(dialog.getByRole('tab', { name: '期权', exact: true })).toHaveAttribute('data-state', 'active');
      await expect(dialog).toContainText('N/A');
      await expect(dialog).toContainText('AAPL261106P00220000');
      await expect(dialog).toContainText('OI 数据日期未知');
      const chart = dialog.locator('.echarts').first();
      await expect(dialog.locator('.echarts')).toHaveCount(2);
      await expect(chart).toBeVisible();
      const sizes = () => dialog.locator('.echarts').evaluateAll(elements => elements.map(element => {
        const bounds = element.getBoundingClientRect();
        return { width: bounds.width, height: bounds.height };
      }));
      const initial = await sizes();
      await page.waitForTimeout(1500); // Wait across multiple ResizeObserver/autoresize cycles.
      const after = await sizes();
      expect(initial.every(size => size.height === 224)).toBe(true);
      expect(after).toEqual(initial);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(errors).toEqual([]);
      await page.screenshot({ path: testInfo.outputPath('options.png'), fullPage: true });
    });
  }
}

test('preview mode reaches the stock detail and hints explain snapshot scores', async ({ page }) => {
  const requested: string[] = [];
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    requested.push(url.pathname + url.search);
    if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: {
      loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} },
    } });
    const preview = url.searchParams.get('view') === 'preview';
    const data = { ...metric, underlying_price: preview ? 225 : 220, trade_date: '2026-10-07' };
    if (url.pathname.endsWith('/options-intelligence')) return route.fulfill({ json: {
      items: [data], view: preview ? 'preview' : 'official', trade_date: '2026-10-07', available_dates: ['2026-10-07'],
    } });
    if (url.pathname.endsWith('/options-intelligence/AAPL.US')) return route.fulfill({ json: {
      symbol: 'AAPL.US', latest: data, daily_history: [{ ...metric, trade_date: '2026-10-07', skew_30d: 0.1 }], events: [], analyses: [], reason: null,
      view: preview ? 'preview' : 'official', trade_date: '2026-10-07', available_dates: ['2026-10-07'],
    } });
    return route.fulfill({ json: {} });
  });
  await page.goto('/research/options-intelligence');
  await page.getByTestId('research-mode-preview').click();
  await expect(page.getByTestId('options-scanner')).toContainText('225');
  await page.getByRole('button', { name: 'AAPL.US', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByTestId('research-mode-preview')).toHaveAttribute('aria-pressed', 'true');
  await expect(dialog.getByRole('button', { name: '解释异常', exact: true })).toBeDisabled();
  await dialog.getByTestId('research-mode-official').click();
  await expect(dialog.getByTestId('options-date')).toBeVisible();
  expect(requested.some(url => url.includes('AAPL.US?view=preview'))).toBe(true);
  const help = dialog.getByRole('button', { name: '查看 看跌保护需求 说明', exact: true }).first();
  await help.hover();
  const hint = page.locator('[data-slot="tooltip-content"]').filter({ hasText: '不是下跌概率' });
  await expect(hint).toBeVisible();
});
