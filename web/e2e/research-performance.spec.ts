import { expect, test } from '@playwright/test';

test('trend preview skips official rows and opens one security without downloading the full preview', async ({ page }) => {
  const requests: string[] = [];
  const summary = { market: 'CN', trade_date: '2026-10-14', market_regime: 'RISK_ON', market_score: 80,
    universe_size: 3795, data_ready_count: 3795, data_coverage: 1, rankable_count: 3795, candidate_count: 1,
    features: {}, score_breakdown: {}, warnings: [] };
  const snapshot = { code: '600519.SH', name: '贵州茅台', trade_date: summary.trade_date, state: 'TRENDING',
    rank: 1, alpha_score: 82.5, features: {}, score_breakdown: {} };
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    requests.push(path);
    if (path.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true,
      user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
    if (path.endsWith('/trend-following/status')) return route.fulfill({ json: {
      trade_date: '2026-10-13', generated_at: '2026-10-13T12:00:00Z',
    } });
    if (path.endsWith('/preview/status')) return route.fulfill({ json: {
      ...summary, status: 'completed', preview_time: '2026-10-14T06:00:00Z', snapshot_count: 3795,
    } });
    if (path.endsWith('/preview/ranking')) return route.fulfill({ json: {
      ...summary, status: 'completed', preview_time: '2026-10-14T06:00:00Z',
      table: { columns: ['code', 'name', 'rank', 'state', 'alpha_score'], feature_columns: [],
        rows: [['600519.SH', '贵州茅台', 1, 'TRENDING', 82.5]] },
    } });
    if (path.endsWith('/preview/stocks/600519.SH')) {
      expect(url.searchParams.get('trade_date')).toBe(summary.trade_date);
      return route.fulfill({ json: { market: 'CN', latest: snapshot, metadata: snapshot, history: [], market_context: summary } });
    }
    if (path.endsWith('/breadth-history')) return route.fulfill({ json: { points: [], warnings: [] } });
    if (path.endsWith('/classification')) return route.fulfill({ json: { memberships: { industries: [] } } });
    return route.fulfill({ json: { items: [], history: [], warnings: [] } });
  });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/research/trend-following');
  await expect(page.getByTestId('trend-row')).toContainText('贵州茅台');
  expect(requests.filter(path => path.endsWith('/auth/status'))).toHaveLength(1);
  expect(requests).not.toContain('/api/v1/trend-following/ranking/table');
  await page.getByTestId('trend-row').click();
  await expect(page.getByTestId('trend-detail')).toContainText('贵州茅台');
  expect(requests.filter(path => path.endsWith('/preview/ranking'))).toHaveLength(1);
  expect(requests.filter(path => path.includes('/preview/stocks/'))).toHaveLength(1);
  expect(requests).not.toContain('/api/v1/trend-following/preview');
  expect(errors).toEqual([]);
});
