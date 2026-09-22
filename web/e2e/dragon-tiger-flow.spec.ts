import { expect, test } from '@playwright/test';
import raw from './fixtures/dragonTigerFlow';

for (const width of [1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`Dragon Tiger ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.addInitScript(t => localStorage.setItem('theme', t), theme);
      const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
        if (url.pathname.endsWith('/dates')) return route.fulfill({ json: [{ trade_date: raw.trade_date, boards: ['all', 'org', 'hot_money'], errors: {}, generated_at: '2026-09-21T11:30:00Z' }] });
        if (url.pathname.endsWith('/overview')) return route.fulfill({ json: { ...raw, board: url.searchParams.get('board') ?? 'all', range_days: Number(url.searchParams.get('range_days') ?? 1) } });
        return route.fulfill({ json: {} });
      });
      await page.goto('/research/dragon-tiger-flow');
      await expect(page.getByRole('heading', { name: '龙虎榜资金流向', exact: true })).toBeVisible();
      await expect(page.getByTestId('module-tabs').getByRole('tab', { name: '龙虎榜资金流向' })).toHaveAttribute('data-state', 'active');
      await expect(page.getByTestId('flow-stock-dialog')).toHaveCount(0);
      await expect(page.getByRole('button', { name: '最近单日', exact: true })).toHaveAttribute('aria-pressed', 'true');
      await expect(page.getByTestId('flow-all-stocks').locator('tbody tr')).toHaveCount(16);
      await expect(page.getByTestId('flow-trajectory')).toHaveCount(0);
      await page.getByRole('button', { name: '5日', exact: true }).click();
      await expect(page.getByTestId('flow-trajectory').locator('canvas')).toHaveCount(1);
      await page.getByTestId('flow-ranking').getByRole('button', { name: /半导体/ }).click();
      await expect(page.getByTestId('flow-paths').locator('canvas')).toHaveCount(2);
      await expect(page.getByTestId('flow-stocks').locator('tbody tr')).toHaveCount(16);
      await page.getByTestId('flow-stocks').getByRole('button', { name: '测试股票1 · 600001.SH', exact: true }).click();
      await expect(page.getByTestId('flow-stock-dialog')).toContainText('1/2');
      await page.keyboard.press('Escape');
      await page.getByRole('button', { name: '机构榜', exact: true }).click();
      await expect(page.getByTestId('flow-status')).toContainText('机构榜');
      await page.getByRole('button', { name: '3日榜截面', exact: true }).click();
      await expect(page.getByTestId('flow-trajectory')).toHaveCount(0);
      await expect(page.getByRole('button', { name: '20日', exact: true })).toHaveCount(0);
      await page.getByRole('button', { name: '仅1日榜', exact: true }).click();
      await expect(page.getByTestId('flow-trajectory')).toBeVisible();
      const download = page.waitForEvent('download');
      await page.getByRole('button', { name: '导出资金截面' }).click();
      expect((await download).suggestedFilename()).toContain('org-1d.json');
      await page.screenshot({ path: testInfo.outputPath(`flow-${width}-${theme}.png`), fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(errors).toEqual([]);
    });
  }
}

test('empty and failure never display demo evidence', async ({ page }) => {
  let fail = true;
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
    if (path.endsWith('/overview')) return fail ? route.fulfill({ status: 503, json: { detail: 'Unavailable' } }) : route.fulfill({ json: { ...raw, concepts: [], evidence: [], complete: false, missing_dates: raw.dates } });
    return route.fulfill({ json: [] });
  });
  await page.goto('/research/dragon-tiger-flow');
  await expect(page.getByRole('button', { name: '重试数据' })).toBeVisible();
  fail = false; await page.getByRole('button', { name: '重试数据' }).click();
  await expect(page.getByText('暂无完整观察数据，请由管理员在任务中心运行或补数。')).toBeVisible();
  await expect(page.getByTestId('flow-stocks')).toHaveCount(0);
});

test('admin submits bounded asynchronous backfill without replacing the displayed batch', async ({ page }) => {
  const requests: unknown[] = [];
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Admin', role: 'admin', extra: {} } } });
    if (path.endsWith('/overview')) return route.fulfill({ json: raw });
    if (path.endsWith('/dates')) return route.fulfill({ json: [] });
    if (path.endsWith('/run')) { requests.push(route.request().postDataJSON()); return route.fulfill({ status: 202, json: { task_id: 'flow-task', status: 'pending' } }); }
    return route.fulfill({ json: {} });
  });
  await page.goto('/research/dragon-tiger-flow');
  await page.getByRole('button', { name: '补齐最近20交易日' }).click();
  await expect(page.getByRole('link', { name: /已提交 flow-task/ })).toBeVisible();
  expect(requests).toEqual([{ backfill_days: 20, missing_only: true }]);
  await expect(page.getByTestId('flow-ranking')).toContainText('半导体');
});
