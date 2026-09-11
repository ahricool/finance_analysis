import { expect, test } from '@playwright/test';

const snapshot = {
  market: 'CN', code: '510300.SH', name: '沪深300ETF', tradeDate: '2026-08-28',
  category: '宽基', theme: '沪深300', riskGroup: 'CN_EQUITY', enabled: true,
  rank: 2, action: 'BUY', state: 'TRENDING', compositeScore: 85,
  referencePrice: 4.8, ma10Ratio: 0.03, ma20Ratio: 0.05,
  rs5D: 0.02, rs10D: 0.04, rs20D: 0.06, scoreComponents: {}, diagnostics: {},
};
const history = [0, 1, 2, 3, 4].map(index => ({
  ...snapshot, tradeDate: `2026-08-${28 - index}`, referencePrice: 4.8 - index * 0.1,
  compositeScore: 85 - index * 3, rank: 2 + index,
  rs5D: 0.02 - index * 0.003, rs10D: 0.04 - index * 0.005, rs20D: 0.06 - index * 0.005,
}));

for (const width of [1280, 1440]) {
  test(`ETF table details render all four history charts at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/api/v1/**', async route => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname.endsWith('/preview/status') || pathname.endsWith('/preview')) {
        await route.fulfill({ status: 404, json: {} });
        return;
      }
      let body: object = {};
      if (pathname === '/api/v1/auth/status') {
        body = { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } };
      } else if (pathname.endsWith('/etf-rotation/dates')) {
        body = { market: 'CN', latest: snapshot.tradeDate, items: [snapshot.tradeDate] };
      } else if (pathname.endsWith('/etf-rotation/ranking') || pathname.endsWith('/etf-rotation/candidates')) {
        body = { market: 'CN', tradeDate: snapshot.tradeDate, universeSize: 1, dataReadyCount: 1,
          dataCoverage: 1, rankableSize: 1, rankableCoverage: 1, warnings: [], marketSnapshot: null, items: [snapshot] };
      } else if (pathname.endsWith('/etf-rotation/510300.SH')) {
        body = { market: 'CN', metadata: snapshot, latest: snapshot, history, marketSnapshot: null };
      }
      await route.fulfill({ json: body });
    });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/research/etf-rotation');
    await page.getByRole('row').filter({ hasText: '510300.SH' }).click();
    const dialog = page.getByTestId('etf-detail-modal');
    await expect(dialog).toBeVisible();
    const charts = dialog.getByTestId('rotation-history-charts');
    await expect(charts.locator('canvas')).toHaveCount(4);
    for (const label of ['价格与均线', '综合得分', '排名', '相对强度']) {
      const chart = charts.getByRole('img', { name: label, exact: true });
      await chart.scrollIntoViewIfNeeded();
      const canvas = chart.locator('canvas');
      await expect(canvas).toBeVisible();
      await expect.poll(async () => (await canvas.boundingBox())?.height ?? 0).toBeGreaterThan(200);
      expect((await canvas.boundingBox())!.width).toBeGreaterThan(180);
    }
    expect(await charts.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await charts.getByRole('img', { name: '价格与均线', exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath('etf-history.png') });
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
    expect(errors).toEqual([]);
  });
}
