import { expect, test } from '@playwright/test';

for (const domain of ['etf-rotation', 'trend-following']) {
  for (const theme of ['light', 'dark']) {
    test(`${domain} freezes headers and names in ${theme}`, async ({ page }) => {
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      await page.route('**/api/v1/**', async route => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith('/preview/status')) {
          await route.fulfill({ status: 404, json: {} });
          return;
        }
        let body: object = { items: [], dates: [], series: [], points: [], warnings: [] };
        if (path.endsWith('/auth/status')) body = { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } };
        if (path.endsWith('/dates')) body = { items: ['2026-09-18'] };
        if (path.endsWith('/ranking')) body = {
          market: 'CN', tradeDate: '2026-09-18', universeSize: 80, dataReadyCount: 80,
          dataCoverage: 1, rankableSize: 80, rankableCount: 80, rankableCoverage: 1,
          marketSnapshot: null, warnings: [], features: {}, candidates: [],
          items: Array.from({ length: 80 }, (_, i) => ({
            market: 'CN', tradeDate: '2026-09-18', code: `TEST${i}.SH`, name: `测试证券 ${i}`,
            rank: i + 1, compositeScore: 100 - i, alphaScore: 100 - i,
            state: 'TRENDING', action: 'HOLD', setup: 'BREAKOUT_20D', trendDurationDays: i,
            rankChange1D: i, rankChange3D: -i, rankChange5D: i * 2,
            features: {}, diagnostics: {}, reasons: [],
          })),
        };
        await route.fulfill({ json: body });
      });
      await page.goto(`/research/${domain}`);
      const scroll = page.getByTestId(domain === 'etf-rotation' ? 'etf-ranking-scroll' : 'trend-ranking-scroll');
      const header = scroll.locator('thead');
      const nameHeader = header.getByRole('columnheader').filter({ has: page.getByRole('button', { name: domain === 'etf-rotation' ? 'ETF' : '股票名称', exact: true }) });
      for (const width of [1280, 1440, 1920]) {
        await page.setViewportSize({ width, height: 900 });
        await scroll.scrollIntoViewIfNeeded();
        await scroll.evaluate(el => { el.scrollTop = 0; el.scrollLeft = 0; });
        const before = (await header.boundingBox())!;
        await scroll.evaluate(el => { el.scrollTop = 300; el.scrollLeft = 900; });
        await expect.poll(() => scroll.evaluate(el => el.scrollTop)).toBe(300);
        const after = (await header.boundingBox())!;
        expect(Math.abs(after.y - before.y)).toBeLessThan(1);
        const viewport = (await scroll.boundingBox())!;
        expect(Math.abs((await nameHeader.boundingBox())!.x - viewport.x)).toBeLessThan(1);
        const name = scroll.locator('tbody [data-column="name"]').nth(8);
        expect(Math.abs((await name.boundingBox())!.x - viewport.x)).toBeLessThan(1);
        const box = (await nameHeader.boundingBox())!;
        expect(await nameHeader.evaluate((el, point) => el.contains(document.elementFromPoint(point.x, point.y)), { x: box.x + 10, y: box.y + 10 })).toBe(true);
      }
      if (domain === 'etf-rotation') {
        await page.getByLabel('排名排序字段').selectOption('rank');
        await expect(scroll.locator('tbody tr').first()).toContainText('TEST0.SH');
        await expect(header.getByRole('columnheader').filter({ has: page.getByRole('button', { name: 'Rank', exact: true }) })).toHaveAttribute('aria-sort', 'ascending');
        await expect(header.getByRole('button', { name: /^Rank Δ/ })).toHaveCount(3);
        await header.getByRole('button', { name: 'Rank Δ 3D', exact: true }).click();
        await expect(scroll.locator('tbody tr').first()).toContainText('TEST0.SH');
        await header.getByRole('button', { name: 'Rank Δ 3D', exact: true }).click();
        await expect(scroll.locator('tbody tr').first()).toContainText('TEST79.SH');
      }
    });
  }
}
