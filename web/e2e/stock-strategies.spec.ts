import { expect, test } from '@playwright/test';
import { detail, overview } from './fixtures/stockStrategies';

for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`stock strategies ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true,
          user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
        if (url.pathname.endsWith('/stock-strategies')) return route.fulfill({ json: overview });
        if (url.pathname.endsWith('/stock-strategies/ma_dd30')) return route.fulfill({ json: detail });
        return route.fulfill({ json: {} });
      });
      await page.goto('/strategies?market=US');
      await expect(page.getByTestId('strategy-row')).toContainText('运行失败');
      await expect(page.getByTestId('strategy-row')).toContainText('2026-10-19');
      await expect(page.getByTestId('strategy-row')).toContainText('测试失败原因');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath('strategy-overview.png'), fullPage: true });
      await page.getByTestId('strategy-row').getByRole('link').click();
      await expect(page).toHaveURL(/strategies\/ma_dd30\?market=US/);
      await expect(page.getByRole('alert')).toContainText('最后成功结算：2026-10-19');
      await expect(page.getByText('当前模拟持仓', { exact: true })).toBeVisible();
      await expect(page.getByTestId('strategy-position').getByRole('button', { name: /AAPL.US.*苹果/ })).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath('strategy-positions.png'), fullPage: true });
      await page.getByRole('button', { name: '每日账本', exact: true }).click();
      await page.getByText('买入 1 · 卖出 0 · 未成交 0 · 查看成交、计划与数据').click();
      await expect(page.getByText(/买入 苹果（AAPL.US）/)).toBeVisible();
      await expect(page.getByTestId('strategy-performance-chart').locator('canvas')).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath('strategy-detail.png'), fullPage: true });
      expect(errors).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.getByRole('radio', { name: 'A股', exact: true }).click();
      await expect(page).toHaveURL(/\/strategies\?market=CN$/);
    });
  }
}

test('overview restores filters and scroll across actual Shell remounts', async ({ page }) => {
  const items = Array.from({ length: 12 }, (_, i) => ({ ...overview.items[0], strategy: { ...overview.items[0]!.strategy, key: `strategy-${i}`, name: `测试策略 ${i + 1}` } }));
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
    if (url.pathname.endsWith('/stock-strategies')) return route.fulfill({ json: { ...overview, items } });
    if (url.pathname.includes('/stock-strategies/')) return route.fulfill({ json: detail });
    return route.fulfill({ json: {} });
  });
  await page.goto('/strategies?market=US&status=failed&search=测试&sort=return_desc');
  const card = page.getByTestId('strategy-row').nth(8);
  await card.scrollIntoViewIfNeeded();
  const offset = await page.evaluate(() => window.scrollY);
  expect(offset).toBeGreaterThan(0);
  await card.getByRole('link').click();
  await page.getByRole('link', { name: '策略列表' }).click();
  await expect(page.getByTestId('strategy-row')).toHaveCount(12);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(offset);
  await expect(page.getByLabel('搜索策略名称')).toHaveValue('测试');
  await expect(page).toHaveURL(/status=failed/);
});
