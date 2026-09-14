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

for (const width of [1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`ETF table details render all four history charts at ${width}px in ${theme}`, async ({ page }, testInfo) => {
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
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
        } else if (pathname.endsWith('/etf-rotation/rank-history')) {
          const dates = Array.from({ length: 44 }, (_, i) => new Date(Date.UTC(2026, 6, 16 + i)))
            .filter(day => day.getUTCDay() !== 0 && day.getUTCDay() !== 6)
            .slice(-30).map(day => day.toISOString().slice(0, 10));
          body = { market: 'CN', dates, officialCount: dates.length, previewDate: null,
            generatedAt: '2026-08-28T10:50:00Z', previewTime: null,
            series: Array.from({ length: 40 }, (_, i) => ({
              code: `ETF${i}.SH`, name: `轮动 ETF ${i + 1}`,
              ranks: dates.map((_, j) => i === 2 && j === 15 ? null : (i + Math.floor(j / 3)) % 40 + 1),
            })),
          };
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
      const rankingChart = page.getByTestId('etf-rank-history');
      await expect(rankingChart.locator('canvas')).toHaveCount(1);
      await rankingChart.scrollIntoViewIfNeeded();
      const chartBox = await rankingChart.locator('canvas').boundingBox();
      expect(chartBox!.height).toBeGreaterThan(300);
      expect(await rankingChart.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
      await rankingChart.screenshot({ path: testInfo.outputPath(`rank-history-${theme}-${width}.png`) });
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
}

test('ETF history labels preview and a history error leaves the table usable', async ({ page }, testInfo) => {
  const previewDate = '2026-08-31';
  const current = { ...snapshot, rank: 1, tradeDate: previewDate };
  let failHistory = false;
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let body: object = {};
    if (path === '/api/v1/auth/status') {
      body = { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } };
    } else if (path.endsWith('/rank-history')) {
      if (failHistory) {
        await route.fulfill({ status: 503, json: { detail: 'History unavailable' } });
        return;
      }
      body = { market: 'CN', dates: [snapshot.tradeDate, previewDate], officialCount: 1,
        previewDate, previewTime: '2026-08-31T06:35:00Z', generatedAt: '2026-08-28T10:50:00Z',
        series: [{ code: snapshot.code, name: snapshot.name, ranks: [2, 1] }],
      };
    } else if (path.endsWith('/preview') || path.endsWith('/preview/status')) {
      body = { status: 'completed', market: 'CN', tradeDate: previewDate,
        previewTime: '2026-08-31T06:35:00Z', dataAsOf: '2026-08-31T06:34:00Z', provider: 'easyquotation_tencent',
        universeSize: 1, dataCoverage: 1, warnings: [], items: [current], marketSnapshot: null,
      };
    } else if (path.endsWith('/ranking')) {
      body = { market: 'CN', tradeDate: snapshot.tradeDate, universeSize: 1, dataReadyCount: 1,
        dataCoverage: 1, rankableSize: 1, rankableCoverage: 1, warnings: [], items: [snapshot], marketSnapshot: null };
    } else if (path.endsWith('/dates')) {
      body = { market: 'CN', latest: snapshot.tradeDate, items: [snapshot.tradeDate] };
    }
    await route.fulfill({ json: body });
  });
  await page.goto('/research/etf-rotation');
  await expect(page.getByTestId('research-mode-preview')).toHaveAttribute('aria-pressed', 'true');
  const chart = page.getByTestId('etf-rank-history');
  await expect(chart).toContainText('最后一个空心点为 Preview');
  await expect(chart.locator('canvas')).toHaveCount(1);
  await chart.screenshot({ path: testInfo.outputPath('rank-history-preview.png') });
  failHistory = true;
  await page.getByTestId('etf-rotation-refresh').click();
  await expect(chart.getByRole('button', { name: '重试排名历史' })).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: snapshot.code })).toBeVisible();
});
