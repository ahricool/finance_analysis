import { compactTrendResponse, isRankingPath } from './researchReadViews';
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

for (const width of [1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`breadth charts stay isolated at ${width} ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      let fail = false;
      const removedRequests: string[] = [];
      await page.route('**/api/v1/**', async route => {
        const url = new URL(route.request().url()), path = url.pathname;
        let body: object = {};
        if (path.includes('/event-study') || path.endsWith('/transitions')) {
          removedRequests.push(path);
          return route.fulfill({status:504,json:{detail:'upstream timeout'}});
        }
        if (path.endsWith('/auth/status')) body = {loggedIn:true,user:{uid:1,username:'Tester',role:'user',extra:{}}};
        else if (path.includes('/preview')) return route.fulfill({status:404,json:{}});
        else if (path.endsWith('/breadth-history')) {
          if (fail) return route.fulfill({status:503,json:{detail:'Breadth unavailable'}});
          expect(url.searchParams.get('days')).toBe('30');
          body = breadth;
        } else if (path.endsWith('/dates')) body = {market:'CN',latest:dates[29],items:[...dates].reverse()};
        else if (isRankingPath(path)) body = {...summary,items:snapshots,candidates:[]};
        else if (path.endsWith('/opportunities')) body = {items:[],status:'not_computed'};
        await route.fulfill({json:compactTrendResponse(path,body)});
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

      await expect(panel.getByTestId('trend-transition')).toHaveCount(0);
      fail = true;
      await page.getByTestId('trend-refresh').click();
      await expect(panel.getByRole('button', { name: '重试趋势广度' })).toBeVisible();
      await expect(page.getByTestId('trend-row')).toHaveCount(12);
      expect(removedRequests).toEqual([]);
      expect(errors).toEqual([]);
    });
  }
}

test('Preview breadth becomes official without restoring transition requests', async ({page}) => {
  const previewDate = '2026-09-29';
  let officialToday = false;
  const removedRequests: string[] = [];
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: object = {};
    if (path.includes('/event-study') || path.endsWith('/transitions')) {
      removedRequests.push(path);
      return route.fulfill({status:504,json:{detail:'upstream timeout'}});
    }
    if (path.endsWith('/auth/status')) body = {loggedIn:true,user:{uid:1,username:'Tester',role:'user',extra:{}}};
    else if (path.endsWith('/breadth-history')) body = {...breadth,previewDate:officialToday?null:previewDate,
      points:[...(officialToday?points.slice(1):points),{...points[29],tradeDate:previewDate,isPreview:!officialToday}]};
    else if (path.includes('/preview')) body = {...summary,status:'completed',tradeDate:previewDate,
      previewTime:'2026-09-29T06:35:00Z',snapshots:snapshots.map(stock=>({...stock,tradeDate:previewDate})),snapshotCount:12,scoreBreakdown:{}};
    else if (isRankingPath(path)) body = {...summary,items:snapshots,candidates:[]};
    else if (path.endsWith('/dates')) body = {items:[...dates].reverse()};
    else if (path.endsWith('/opportunities')) body = {items:[],status:'not_computed'};
    await route.fulfill({json:compactTrendResponse(path,body)});
  });
  await page.goto('/research/trend-following');
  const panel = page.getByTestId('trend-market-overview');
  await expect(panel).toContainText('+ 1 Preview');
  await expect(panel.locator('canvas')).toHaveCount(2);
  officialToday = true;
  await page.getByTestId('trend-refresh').click();
  await expect(panel).not.toContainText('+ 1 Preview');
  await expect(panel.locator('canvas')).toHaveCount(2);
  expect(removedRequests).toEqual([]);
});
