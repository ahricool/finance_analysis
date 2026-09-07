import { expect, test } from '@playwright/test';

const snapshot = {
  market: 'CN', code: '000001.SZ', name: '平安银行', tradeDate: '2026-08-28',
  rank: 12, rankChange1D: 5, rankChange3D: -2, rankChange5D: 0,
  state: 'ENTRY', action: 'ENTRY', setup: 'BREAKOUT_20D', alphaScore: 79,
  trendScore: 80, rsScore: 78, breakoutScore: 76, referencePrice: 110, atr: 2,
  features: {}, scoreBreakdown: { trend: 80, relativeStrength: 78 }, reasons: ['趋势走强'],
};
const summary = {
  market: 'CN', tradeDate: snapshot.tradeDate, marketRegime: 'RISK_ON', marketScore: 82,
  suggestedMaxExposure: 0.8, universeSize: 800, dataReadyCount: 790, dataCoverage: 0.9875,
  rankableCount: 480, candidateCount: 1, entryCount: 1, warnings: [], features: {},
};
const history = [12, 17, 14, 28, 35, 31, 46, 40, 52, 63].map((rank, index) => ({
  ...snapshot, rank, tradeDate: `2026-08-${28 - index}`,
}));

for (const width of [360, 1280]) {
  for (const theme of ['light', 'dark']) {
    test(`trend detail is centered and readable at ${width}px in ${theme} mode`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      await page.route('**/api/v1/**', async route => {
        const pathname = new URL(route.request().url()).pathname;
        let body: object = {};
        if (pathname === '/api/v1/auth/status') {
          body = { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } };
        } else if (pathname.endsWith('/trend-following/dates')) {
          body = { market: 'CN', latest: snapshot.tradeDate, items: [snapshot.tradeDate] };
        } else if (pathname.endsWith('/trend-following/ranking')) {
          body = { ...summary, items: [snapshot] };
        } else if (pathname.endsWith('/trend-following/candidates')) {
          body = { ...summary, items: [snapshot] };
        } else if (pathname.endsWith('/trend-following/portfolio')) {
          body = { ...summary, positions: [], maxExposure: 0.8, currentExposure: 0, positionCount: 0 };
        } else if (pathname.endsWith('/trend-following/000001.SZ')) {
          body = { market: 'CN', metadata: snapshot, latest: snapshot, history, marketContext: summary };
        }
        await route.fulfill({ json: body });
      });
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto('/market/trend-following');
      const changes = page.getByTestId('trend-rank-changes');
      await expect(changes.locator('.text-market-up')).toHaveText('+5');
      await expect(changes.locator('.text-market-down')).toHaveText('-2');
      const headerBefore = await page.locator('header').first().boundingBox();
      const before = await page.locator('body').evaluate(el => ({ overflow: el.style.overflow, paddingRight: el.style.paddingRight }));
      await page.getByTestId('trend-candidate').click();
      const dialog = page.getByRole('dialog');
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole('heading', { name: '平安银行' })).toBeVisible();
      const canvas = dialog.getByTestId('trend-rank-history').locator('canvas');
      await expect(canvas).toBeVisible();
      // Wait for the opening scale animation before measuring the centered panel.
      await expect.poll(async () => {
        const box = (await dialog.boundingBox())!;
        return Math.abs(box.x + box.width / 2 - width / 2);
      }).toBeLessThan(2);
      const box = (await dialog.boundingBox())!;
      expect(Math.abs(box.y + box.height / 2 - 450)).toBeLessThan(2);
      expect(box.width).toBeLessThanOrEqual(width - 30);
      expect(box.y).toBeGreaterThanOrEqual(width < 640 ? 7 : 14);
      expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
      const headerAfter = await page.locator('header').first().boundingBox();
      expect(headerAfter!.x).toBe(headerBefore!.x);
      expect(headerAfter!.width).toBe(headerBefore!.width);
      await page.screenshot({ path: testInfo.outputPath('trend-dialog.png') });
      await canvas.hover({ position: { x: 90, y: 80 } });
      await expect(dialog.getByText('Alpha Rank', { exact: true })).toBeVisible();
      await dialog.getByTestId('trend-history').last().scrollIntoViewIfNeeded();
      await expect(dialog.getByTestId('trend-history').last()).toContainText('排名 #63');
      await page.keyboard.press('Escape');
      await expect(dialog).not.toBeVisible();
      await expect(page.getByTestId('trend-candidate')).toBeFocused();
      expect(await page.locator('body').evaluate(el => ({ overflow: el.style.overflow, paddingRight: el.style.paddingRight }))).toEqual(before);
      await page.getByTestId('trend-candidate').click();
      await expect(dialog).toBeVisible();
      await dialog.getByRole('button', { name: 'Close', exact: true }).click();
      await expect(dialog).not.toBeVisible();
      expect(errors).toEqual([]);
    });
  }
}
