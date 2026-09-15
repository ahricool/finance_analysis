import { expect, test } from '@playwright/test';

const dates = Array.from({ length: 30 }, (_, i) => new Date(Date.UTC(2026, 6, 31 + i * 2)).toISOString().slice(0, 10));
const snapshots = Array.from({ length: 12 }, (_, i) => ({
  market: 'CN', code: `${String(i + 1).padStart(6, '0')}.SZ`, name: ['中际旭创', '新易盛', '工业富联', '寒武纪'][i % 4],
  tradeDate: dates[29], rank: i + 1, state: 'TRENDING', alphaScore: 86.3,
  trendScore: 82.6, rsScore: 79.4, fragilityScore: 18.5, trendDurationDays: 14,
  features: {}, scoreBreakdown: {}, fragilityBreakdown: {}, reasons: [], referencePrice: 110,
}));
const summary = { market: 'CN', tradeDate: dates[29], marketRegime: 'RISK_ON', marketScore: 82,
  universeSize: 3800, dataReadyCount: 3700, dataCoverage: 0.98,
  rankableCount: 3700, candidateCount: 50, warnings: [], features: {},
};
const points = dates.map((tradeDate, i) => ({ tradeDate, rankableCount: 3700,
  trendBreadth: 0.32 + i * 0.007, participation: 0.38 + i * 0.007,
  deteriorationBreadth: 0.2 - i * 0.002, inactive: 0.42 - i * 0.005,
  emerging: 0.06, healthy: 0.32 + i * 0.007, deteriorating: 0.2 - i * 0.002,
  coverage: 1, warning: null, isPreview: false }));
const breadth = { market: 'CN', dates, officialCount: 30, previewDate: null,
  previewTime: null, generatedAt: '2026-09-27T10:50:00Z', warnings: [], points };
const items = snapshots.slice(0, 4).map((stock, i) => ({
  code: stock.code, name: stock.name, previousState: i < 2 ? 'CANDIDATE' : 'TRENDING',
  currentState: i < 2 ? 'TRENDING' : 'WEAKENING', previousDate: dates[27], tradeDate: dates[28],
  previousRank: i + 12, currentRank: i + 5, rankDelta: 7, direction: i < 2 ? 'strengthening' : 'deteriorating',
  priority: 0, isPreview: false,
}));

for (const width of [1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`breadth charts, filters and point-in-time detail at ${width} ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      let fail = false;
      const requestedDetails: string[] = [];
      await page.route('**/api/v1/**', async route => {
        const url = new URL(route.request().url());
        const path = url.pathname;
        let body: object = {};
        if (path === '/api/v1/auth/status') body = { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } };
        else if (path.endsWith('/preview/status') || path.endsWith('/preview')) {
          await route.fulfill({ status: 404, json: {} }); return;
        } else if (path.endsWith('/breadth-history')) {
          if (fail) { await route.fulfill({ status: 503, json: { detail: 'Breadth unavailable' } }); return; }
          expect(url.searchParams.get('days')).toBe('30');
          body = breadth;
        } else if (path.endsWith('/transitions')) {
          const direction = url.searchParams.get('direction');
          body = { market: 'CN', days: Number(url.searchParams.get('days')), warnings: [],
            items: direction === 'all' ? items : items.filter(item => item.direction === direction) };
        } else if (path.endsWith('/dates')) body = { market: 'CN', latest: dates[29], items: [...dates].reverse() };
        else if (path.endsWith('/ranking')) body = { ...summary, items: snapshots, candidates: [] };
        else {
          const code = decodeURIComponent(path.split('/').pop()!);
          const stock = snapshots.find(item => item.code === code);
          if (stock) {
            requestedDetails.push(code);
            expect(url.searchParams.get('trade_date')).toBe(dates[28]);
            body = { market: 'CN', metadata: stock, latest: { ...stock, tradeDate: dates[28] }, marketContext: summary,
              history: dates.slice(0, -1).map(tradeDate => ({ ...stock, tradeDate })) };
          }
        }
        await route.fulfill({ json: body });
      });
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto('/research/trend-following');
      const panel = page.getByTestId('trend-market-overview');
      await expect(panel.locator('canvas')).toHaveCount(2);
      await panel.scrollIntoViewIfNeeded();
      expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
      await expect(panel.getByTestId('trend-kpi-trendBreadth')).toContainText('52.3%');
      await expect(panel.getByTestId('trend-kpi-trendBreadth')).toContainText('+3.5pp');
      const boxes = await panel.locator('canvas').evaluateAll(els => els.map(el => {
        const box = el.getBoundingClientRect(); return { x: box.x, y: box.y, width: box.width, height: box.height };
      }));
      expect(boxes[0]!.height).toBe(280);
      expect(boxes[1]!.x).toBeGreaterThan(boxes[0]!.x + boxes[0]!.width);
      const box = boxes[0]!;
      await page.mouse.move(box.x + box.width / 2, box.y + 130);
      await panel.screenshot({ path: testInfo.outputPath(`breadth-${theme}-${width}.png`) });
      await expect(panel.getByTestId('trend-transition')).toHaveCount(4);
      await panel.getByRole('button', { name: '转弱', exact: true }).click();
      await expect(panel.getByTestId('trend-transition')).toHaveCount(2);
      await panel.getByRole('button', { name: '5D', exact: true }).click();
      await expect(panel.getByTestId('trend-transitions')).toContainText('最近 5 个正式');
      await panel.getByTestId('trend-transition').first().click();
      await expect(page.getByTestId('trend-detail')).toBeVisible();
      await expect(page.getByTestId('trend-rank-history')).toBeVisible();
      await expect(page.getByTestId('trend-fragility-history')).toBeVisible();
      expect(requestedDetails[0]).toBe(snapshots[2]!.code);
      await page.keyboard.press('Escape');
      fail = true;
      await page.getByTestId('trend-refresh').click();
      await expect(panel.getByRole('button', { name: '重试趋势广度' })).toBeVisible();
      await expect(page.getByTestId('trend-row')).toHaveCount(12);
      expect(errors).toEqual([]);
    });
  }
}

test('Preview is an extra point and same-day official transitions open official detail', async ({ page }, testInfo) => {
  const previewDate = '2026-09-29';
  let officialToday = false;
  const previewSnapshots = snapshots.map(stock => ({ ...stock, tradeDate: previewDate, state: 'WEAKENING' }));
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let body: object = {};
    if (path === '/api/v1/auth/status') body = { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } };
    else if (path.endsWith('/breadth-history')) {
      body = { ...breadth, previewDate: officialToday ? null : previewDate,
        points: [...(officialToday ? points.slice(1) : points), { ...points[29], tradeDate: previewDate, isPreview: !officialToday }],
      };
    } else if (path.endsWith('/transitions')) {
      body = { days: 3, warnings: [], previewDate: officialToday ? null : previewDate,
        items: [{ ...items[0], tradeDate: previewDate, isPreview: !officialToday }] };
    } else if (path.endsWith('/preview/status') || path.endsWith('/preview')) {
      body = { ...summary, status: 'completed', tradeDate: previewDate, previewTime: '2026-09-29T06:35:00Z',
        snapshots: previewSnapshots, snapshotCount: 12, scoreBreakdown: {},
      };
    } else if (path.endsWith('/ranking')) body = { ...summary, items: snapshots, candidates: [] };
    else if (path.endsWith('/dates')) body = { market: 'CN', latest: dates[29], items: [...dates].reverse() };
    else if (path.endsWith('/000001.SZ')) {
      expect(url.searchParams.get('trade_date') ?? url.searchParams.get('before_trade_date')).toBe(previewDate);
      body = { market: 'CN', metadata: snapshots[0], latest: snapshots[0], marketContext: summary,
        history: dates.map(tradeDate => ({ ...snapshots[0], tradeDate })) };
    }
    await route.fulfill({ json: body });
  });
  await page.goto('/research/trend-following');
  const panel = page.getByTestId('trend-market-overview');
  await expect(panel).toContainText('+ 1 Preview');
  await expect(panel.getByTestId('trend-transition')).toContainText('Preview');
  await expect(panel.locator('canvas')).toHaveCount(2);
  await panel.screenshot({ path: testInfo.outputPath('breadth-preview.png') });
  await panel.getByTestId('trend-transition').click();
  await expect(page.getByTestId('trend-detail')).toBeVisible();
  await expect(page.getByTestId('trend-detail')).toContainText('当前详情为 Preview');
  await page.keyboard.press('Escape');
  officialToday = true;
  await page.getByTestId('trend-refresh').click();
  await expect(panel).not.toContainText('+ 1 Preview');
  await expect(panel.getByTestId('trend-transition')).not.toContainText('Preview');
  await panel.getByTestId('trend-transition').click();
  await expect(page.getByTestId('trend-detail')).toBeVisible();
  await expect(page.getByTestId('trend-detail')).not.toContainText('当前详情为 Preview');
  await expect(page.getByTestId('trend-rank-history')).toBeVisible();
});
