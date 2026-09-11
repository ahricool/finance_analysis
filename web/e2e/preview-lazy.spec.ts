import { expect, test } from '@playwright/test';

for (const domain of ['trend-following', 'etf-rotation']) {
  test(`${domain} downloads full Preview only on demand and reuses it`, async ({ page }) => {
    const requests: string[] = [];
    const summary = {
      market: 'CN', trade_date: '2026-09-11', generated_at: '2026-09-11T08:00:00Z',
      universe_size: 0, data_ready_count: 0, data_coverage: 0, rankable_count: 0,
      rankable_size: 0, rankable_coverage: 0, candidate_count: 0, entry_count: 0,
      market_regime: 'RISK_ON', market_score: 80, suggested_max_exposure: 0.8, warnings: [],
    };
    const status = {
      market: 'CN', status: 'completed', trade_date: '2026-09-11',
      preview_time: '2026-09-11T06:00:00Z', data_as_of: '2026-09-11T05:59:00Z',
      provider: 'easyquotation_tencent', snapshot_count: 0, warnings: [],
    };
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      requests.push(path);
      let body: object = {};
      if (path.endsWith('/auth/status')) {
        body = { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } };
      } else if (path.endsWith('/preview/status')) body = status;
      else if (path.endsWith('/preview')) body = { ...summary, ...status, snapshots: [], items: [], market_snapshot: null };
      else if (path.endsWith('/dates')) body = { market: 'CN', latest: summary.trade_date, items: [summary.trade_date] };
      else if (path.endsWith('/ranking')) body = {
        ...summary, items: [], candidates: [], market_snapshot: null,
        portfolio: { ...summary, positions: [], position_count: 0, current_exposure: 0, max_exposure: 0.8 },
      };
      await route.fulfill({ json: body });
    });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`/research/${domain}`);
    const fullCount = () => requests.filter(path => path.endsWith('/preview')).length;
    const statusCount = () => requests.filter(path => path.endsWith('/preview/status')).length;
    await expect(page.getByTestId('research-mode-preview')).toBeEnabled();
    await expect(page.getByTestId('research-data-status')).toHaveAttribute('data-mode', 'official');
    expect(statusCount()).toBe(1);
    expect(fullCount()).toBe(0);
    expect(requests.filter(path => path.endsWith('/ranking'))).toHaveLength(1);
    expect(requests.some(path => path.endsWith('/candidates'))).toBe(false);

    await page.getByTestId('research-mode-preview').click();
    await expect(page.getByTestId('research-provider')).toHaveText('Tencent');
    await expect(page.getByText('正在加载盘中预演…')).not.toBeVisible();
    expect(fullCount()).toBe(1);
    await page.getByTestId('research-mode-official').click();
    const refresh = page.getByTestId(domain === 'trend-following' ? 'trend-refresh' : 'etf-rotation-refresh');
    await refresh.click();
    await expect.poll(statusCount).toBe(2);
    await expect(refresh).toBeEnabled();
    expect(fullCount()).toBe(1);
    await page.getByTestId('research-mode-preview').click();
    await expect(page.getByText('正在加载盘中预演…')).not.toBeVisible();
    expect(fullCount()).toBe(1);
    await refresh.click();
    await expect.poll(fullCount).toBe(2);
    expect(statusCount()).toBe(3);
    expect(errors).toEqual([]);
  });
}
