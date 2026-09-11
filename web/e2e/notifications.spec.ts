import { expect, test } from '@playwright/test';
import { dashboardResponse } from '../tests/fixtures/dashboard';

for (const width of [1280, 1440, 1920]) {
  test(`message center and Markdown detail at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.addInitScript(() => localStorage.setItem('theme', 'light'));
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/v1/**', async route => {
      const url = new URL(route.request().url());
      const message = { id: 1, uid: null, title: '美股盘后复盘', route_type: 'report', severity: 'info', created_at: '2026-09-11T08:00:00Z' };
      if (url.pathname === '/api/v1/notifications') return route.fulfill({ json: {
        items: [{ ...message, content_preview: '市场走势与风险提示，关注下一交易日的重要财经事件。' }], total: 1, page: 1, page_size: 20,
      } });
      if (url.pathname === '/api/v1/notifications/1') return route.fulfill({ json: {
        ...message, content: '# 市场复盘\n\n## 主要观察\n\n- 关注成交量变化\n- 跟踪财报事件\n\n| 指标 | 状态 |\n| --- | --- |\n| 风险 | 中性 |\n\n<script>throw new Error("unsafe")</script>',
      } });
      return route.fulfill({ json: dashboardResponse(url) });
    });
    await page.goto('/notifications');
    await page.getByRole('button', { name: '打开用户菜单' }).click();
    await expect(page.getByTestId('notification-center-link')).toBeVisible();
    await expect(page.getByTestId('desktop-main-nav').getByText('消息中心')).toHaveCount(0);
    await page.getByTestId('notification-center-link').click();
    await expect(page.getByRole('heading', { name: '消息中心', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '美股盘后复盘', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`notifications-${width}.png`), fullPage: true, animations: 'disabled' });
    await page.getByRole('button', { name: '美股盘后复盘', exact: true }).click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByRole('heading', { name: '主要观察', exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`notification-detail-${width}.png`), fullPage: true, animations: 'disabled' });
    expect(errors).toEqual([]);
  });
}
