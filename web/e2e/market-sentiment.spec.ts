import { test, expect } from '@playwright/test';
const observation = {
  trade_date: '2026-09-16', previous_trade_date: '2026-09-15', rule_version: 'fa-market-sentiment-v1', scope: 'main', early_time_threshold: '10:00',
  state: 'ACTIVE', heat_score: 72.5, state_reasons: ['热度72.5≥60'], upstream_total: 42, excluded_st_count: 3, excluded_new_count: 1, excluded_union_count: 4,
  unknown_scope_count: 0, scope_complete: true, boards_complete: true, limit_up_count: 38, first_board_count: 25, multi_board_count: 13, highest_board: 8,
  board_distribution: { '1': 25, '2': 6, '3': 3, '4': 2, '5': 1, '6': 0, '7+': 1 }, unconfirmed_board_count: 0,
  early_limit_up_count: 20, valid_limit_up_time_count: 38, time_coverage: 1, early_limit_up_ratio: 20 / 38,
  seal_retention_median: .63, valid_seal_retention_count: 36, seal_retention_coverage: 36 / 38, seal_money_sum: 1230000000,
  valid_seal_money_count: 38, seal_money_coverage: 1, reasons: [{ reason: '测试原因甲', count: 20 }, { reason: '测试原因乙', count: 18 }],
  promotions: Object.fromEntries(['1_to_2', '2_to_3', '3_to_4', 'multi'].map(k => [k, { source_date: '2026-09-15', target_date: '2026-09-16', complete: true, numerator: 3, denominator: 8, ratio: 3 / 8, promoted_codes: ['000001.SZ'], not_promoted_codes: ['000002.SZ'] }])),
  changes: { limit_up_count: 5, first_board_count: 2, multi_board_count: 3, highest_board: 0, early_limit_up_ratio: -.02, seal_retention_median: .03, heat_score: 7.5 },
  quality: { optional_errors: { limit_break: 'FuyaoError' } }, supplements: {}, source_timestamp: '2026-09-16T07:00:00Z', fetched_at: '2026-09-16T11:20:00Z', generated_at: '2026-09-16T11:21:00Z',
};
for (const width of [1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`sentiment ${width}px ${theme} desktop`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(theme => localStorage.setItem('theme', theme), theme);
      const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
      await page.route('**/api/v1/**', async route => {
        const url = new URL(route.request().url()); const path = url.pathname;
        const selected = url.searchParams.get('trade_date') || observation.trade_date;
        let body: unknown = {};
        if (path.endsWith('/auth/status')) body = { loggedIn: true, user: { uid: 1, username: 'Test', email: 'test@example.com', role: 'user', avatarUrl: null } };
        if (path.endsWith('/dates')) body = ['2026-09-16'];
        if (path.endsWith('/overview')) body = { trade_date: selected, expected_trade_date: '2026-09-16', observation: selected === '2026-09-16' ? observation : null, industry_top: [] };
        if (path.endsWith('/history')) body = { dates: ['2026-09-14', '2026-09-15', '2026-09-16'], items: [null, { ...observation, trade_date: '2026-09-15' }, observation] };
        if (path.endsWith('/ladder')) body = { source: null };
        if (path.endsWith('/pool')) body = { trade_date: selected, kind: url.searchParams.get('kind') || 'limit_up', available: true, total: 1, upstream_total: 42, page: 1, size: 50, basis: 'main', items: [{ thscode: '000001.SZ', name: '测试股票', continue_day_text: '2连板', consecutive_boards: 2, price_change_ratio: .1, limit_up_time: '09:40', seal_money: 10000000, max_seal_money: 20000000, seal_retention: .5, limit_up_reason: '测试原因甲', is_st: false, is_new: false }] };
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
      });
      await page.goto('/research/market-sentiment');
      await expect(page.getByTestId('market-sentiment-page')).toBeVisible();
      await expect(page.getByText('活跃', { exact: true })).toBeVisible();
      await expect(page.getByText('测试股票')).toBeVisible();
      await expect(page.locator('canvas')).toHaveCount(4);
      expect(errors).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await page.screenshot({ path: info.outputPath(`sentiment-${width}-${theme}.png`), fullPage: true });
      await page.getByRole('button', { name: '09-14', exact: true }).click();
      await expect(page.getByTestId('sentiment-empty')).toContainText('2026-09-14');
    });
  }
}
