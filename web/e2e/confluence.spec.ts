import { expect, test } from '@playwright/test';
import raw from './fixtures/confluence';

for (const width of [1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`Confluence evidence ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.addInitScript(t => localStorage.setItem('theme', t), theme);
      const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
        if (url.pathname.endsWith('/dates')) return route.fulfill({ json: ['2026-09-22'] });
        if (url.pathname.endsWith('/ranking')) return route.fulfill({ json: raw });
        return route.fulfill({ json: {} });
      });
      await page.goto('/research/confluence');
      await expect(page.getByTestId('module-tabs').getByRole('tab', { name: '多信号共振' })).toHaveAttribute('data-state', 'active');
      await expect(page.getByRole('table')).toContainText('88.2');
      await expect(page.getByRole('table')).toContainText('3/4');
      await expect(page.getByRole('table')).toContainText('2026-09-21');
      await expect(page.getByRole('table')).toContainText('ETF 无数据');
      await page.getByRole('button', { name: /测试股票/ }).click();
      const dialog = page.getByRole('dialog');
      await expect(dialog).toContainText('25/25');
      await expect(dialog).toContainText('12 → 4');
      await expect(dialog).toContainText('10/20');
      await expect(dialog).toContainText('游资 缺失');
      await expect(dialog).toContainText('Why Confluence');
      await page.screenshot({ path: testInfo.outputPath(`confluence-detail-${width}-${theme}.png`), fullPage: true });
      await page.keyboard.press('Escape');
      await page.screenshot({ path: testInfo.outputPath(`confluence-${width}-${theme}.png`), fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(errors).toEqual([]);
    });
  }
}

test('filters, partial US coverage and failed request clear old data', async ({ page }) => {
  let fail = false; const params: URLSearchParams[] = [];
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
    if (url.pathname.endsWith('/dates')) return route.fulfill({ json: ['2026-09-22'] });
    if (url.pathname.endsWith('/ranking')) {
      params.push(url.searchParams);
      return fail ? route.fulfill({ status: 503, json: { detail: 'Unavailable' } }) : route.fulfill({ json: url.searchParams.get('market') === 'US' ? { ...raw, market: 'US', items: [], total: 0 } : raw });
    }
    return route.fulfill({ json: {} });
  });
  await page.goto('/research/confluence');
  await expect(page.getByRole('table')).toContainText('测试股票');
  await page.getByLabel('最低有效维度', { exact: true }).fill('4');
  await page.getByLabel('最低分数', { exact: true }).fill('80');
  await page.getByLabel('仅 IGNITION / EMERGING').check();
  await page.getByRole('button', { name: '筛选', exact: true }).click();
  await expect.poll(() => params.at(-1)?.get('min_signals')).toBe('4');
  expect(params.at(-1)?.get('min_score')).toBe('80');
  expect(params.at(-1)?.get('early_only')).toBe('true');
  await page.getByRole('combobox', { name: '市场', exact: true }).selectOption('US');
  await expect(page.getByRole('table')).toContainText('没有满足当前条件');
  await expect(page.getByText(/US 当前可能仅有/)).toBeVisible();
  fail = true;
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(page.getByRole('table')).toHaveCount(0);
});
