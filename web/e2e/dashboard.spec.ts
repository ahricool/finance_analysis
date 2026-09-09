import { expect, test } from '@playwright/test';
import { dashboardResponse } from '../tests/fixtures/dashboard';

for (const width of [1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`public dashboard at ${width}px in ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.clock.setFixedTime(new Date('2026-09-09T08:00:00Z'));
      await page.addInitScript(value => { localStorage.setItem('theme', value); localStorage.setItem('display_timezone', 'Asia/Shanghai'); }, theme);
      const unexpected: string[] = [];
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/api/v1/**', async route => {
        try { await route.fulfill({ json: dashboardResponse(new URL(route.request().url())) }); }
        catch { unexpected.push(route.request().url()); await route.fulfill({ status: 404, json: {} }); }
      });
      await page.goto('/');
      await expect(page).toHaveURL(/\/dashboard$/);
      await expect(page.getByRole('heading', { name: '市场动态', exact: true })).toBeVisible();
      await expect(page.getByTestId('desktop-main-nav').getByRole('link', { name: '动态', exact: true })).toBeVisible();
      await expect(page.getByTestId('dashboard-feed-item')).toHaveCount(8);
      await expect(page.getByTestId('dashboard-feed-item').first()).toContainText('ORCL FY27 Q1');
      await expect(page.getByText('114,820', { exact: false })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      expect(unexpected).toEqual([]); expect(errors).toEqual([]);
      await page.screenshot({ path: testInfo.outputPath(`dashboard-${width}-${theme}.png`), fullPage: true });
    });
  }
}

test('login defaults to the public dashboard without requesting private market data', async ({ page }) => {
  let loggedIn = false;
  const unexpected: string[] = [];
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/auth/status' && !loggedIn) return route.fulfill({ json: { loggedIn: false, user: null } });
    if (url.pathname === '/api/v1/auth/lookup') return route.fulfill({ json: { ok: true, needsPasswordSetup: false } });
    if (url.pathname === '/api/v1/auth/login') { loggedIn = true; return route.fulfill({ json: { ok: true } }); }
    try { return route.fulfill({ json: dashboardResponse(url) }); }
    catch { unexpected.push(url.pathname); return route.fulfill({ status: 404, json: {} }); }
  });
  await page.goto('/login');
  await page.getByTestId('login-email').fill('reviewer@example.com');
  await page.getByTestId('login-submit').click();
  await page.getByTestId('login-password').fill('test-password');
  await page.getByTestId('login-submit').click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByTestId('dashboard-feed-item')).toHaveCount(8);
  expect(unexpected).toEqual([]);
});
