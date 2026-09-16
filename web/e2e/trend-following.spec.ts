import { expect, test } from '@playwright/test';

const snapshot = {
  market: 'CN', code: '000001.SZ', name: '平安银行', tradeDate: '2026-08-28',
  rank: 12, rankChange1D: 5, rankChange3D: -2, rankChange5D: 0,
  state: 'TRENDING', setup: 'BREAKOUT_20D', alphaScore: 82.5,
  trendScore: 80, rsScore: 78, breakoutScore: 80, referencePrice: 110, atr: 2,
  trendDurationDays: 13, trendLifecycle: 'EXPANSION', fragilityScore: 18,
  fragilityBreakdown: { accelerationDecay: 12, qualityDecay: 15, efficiencyDecay: 20, relativeStrengthDecay: 18, rankDecay: 24, priceStructureRisk: 15 },
  features: { alphaVersion: 2, pathScore: 95, setupScore: 80, weightedR2: .98, weightedSlopePercentile: 92,
    positiveReturnConcentration: .3, atrExpansionRatio: 1.1, downsideControlQuality: 90, downsideUpsideRatio: .10536,
    trendQuality: 87, trendAcceleration: 0.12, signedEfficiencyRatio10D: 0.71, priorCompression: true,
    r2Quality: 98, momentumQuality: 74, return10DQuality: 72, return20DQuality: 70, drawdownQuality: 81,
    rs5DQuality: 55, rs10DQuality: 61, rs20DQuality: 58,
    breakoutQuality: 77, extensionQuality: 66, volumeQuality: 80, compressionQuality: 40,
    concentrationQuality: 88, volatilityQuality: 72,
    alphaTrendContribution: 32, alphaRsContribution: 19.5, alphaSetupContribution: 12, alphaPathContribution: 19 }, scoreBreakdown: { alpha: { version: 2,
    components: { trend: 80, rs: 78, setup: 80, path: 95 },
    weights: { trend: .4, rs: .25, setup: .15, path: .2 },
    contributions: { trend: 32, rs: 19.5, setup: 12, path: 19 }, score: 82.5 } }, reasons: ['趋势走强'],
};
const summary = {
  market: 'CN', tradeDate: snapshot.tradeDate, marketRegime: 'RISK_ON', marketScore: 82,
  universeSize: 800, dataReadyCount: 790, dataCoverage: 0.9875,
  rankableCount: 480, candidateCount: 1, warnings: [], features: {},
};
const history = [12, 17, 14, 28, 35, 31, 46, 40, 52, 63].map((rank, index) => ({
  ...snapshot, rank, fragilityScore: index === 3 ? null : 18 + index * 4, tradeDate: `2026-08-${28 - index}`,
}));

for (const width of [1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`trend detail is centered and readable at ${width}px in ${theme} mode`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      await page.route('**/api/v1/**', async route => {
        const pathname = new URL(route.request().url()).pathname;
        if (pathname.endsWith('/preview/status') || pathname.endsWith('/preview')) {
          await route.fulfill({ status: 404, json: {} });
          return;
        }
        let body: object = {};
        if (pathname === '/api/v1/auth/status') {
          body = { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } };
        } else if (pathname.endsWith('/trend-following/breadth-history')) {
          body = { market: 'CN', points: [], dates: [], officialCount: 0, warnings: [] };
        } else if (pathname.endsWith('/trend-following/transitions')) {
          body = { market: 'CN', days: 3, items: [], warnings: [] };
        } else if (pathname.endsWith('/trend-following/dates')) {
          body = { market: 'CN', latest: snapshot.tradeDate, items: [snapshot.tradeDate] };
        } else if (pathname.endsWith('/trend-following/state-history')) {
          body = { market: 'CN', anchorDate: null, dates: [], items: [], officialCount: 0, warnings: [] };
        } else if (pathname.endsWith('/trend-following/ranking')) {
          body = { ...summary, items: [snapshot], candidates: [snapshot] };
        } else if (pathname.endsWith('/trend-following/candidates')) {
          body = { ...summary, items: [snapshot], candidates: [snapshot] };
        } else if (pathname.endsWith('/trend-following/000001.SZ')) {
          body = { market: 'CN', metadata: snapshot, latest: snapshot, history, marketContext: summary };
        }
        await route.fulfill({ json: body });
      });
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto('/research/trend-following');
      const changes = page.getByTestId('trend-rank-changes');
      await expect(changes.locator('.text-market-up')).toHaveText('+5');
      await expect(changes.locator('.text-market-down')).toHaveText('-2');
      const headerBefore = await page.locator('header').first().boundingBox();
      const before = await page.locator('body').evaluate(el => ({ overflow: el.style.overflow, paddingRight: el.style.paddingRight }));
      await expect(page.getByRole('columnheader', { name: 'Path Score' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Setup Score' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'R² Quality' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Trend Contribution' })).toBeVisible();
      await expect(page.getByText('Signals / Explain')).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Prior Compression' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Breakout Score' })).toHaveCount(0);
      await expect(page.getByText('趋势观察')).toHaveCount(0);
      await page.getByTestId('trend-row').first().click();
      const dialog = page.getByRole('dialog');
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole('heading', { name: '平安银行' })).toBeVisible();
      await expect(dialog.getByTestId('trend-path-detail')).toContainText('Alpha V2');
      const canvas = dialog.getByTestId('trend-rank-history').locator('canvas');
      await expect(canvas).toBeVisible();
      await expect(dialog.getByTestId('trend-fragility-history').locator('canvas')).toBeVisible();
      await expect(dialog.getByText('EXPANSION', { exact: true })).toBeVisible();
      // Wait for the opening scale animation before measuring the centered panel.
      // `left: 50%` follows the content box after scrollbar-gutter, not the visual viewport.
      await expect.poll(async () => {
        const box = (await dialog.boundingBox())!;
        const contentWidth = await page.evaluate(() => document.body.clientWidth);
        return Math.abs(box.x + box.width / 2 - contentWidth / 2);
      }).toBeLessThan(2);
      const box = (await dialog.boundingBox())!;
      expect(Math.abs(box.y + box.height / 2 - 450)).toBeLessThan(2);
      expect(box.width).toBeLessThanOrEqual(width - 30);
      expect(box.y).toBeGreaterThanOrEqual(14);
      expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
      const headerAfter = await page.locator('header').first().boundingBox();
      expect(headerAfter!.x).toBe(headerBefore!.x);
      expect(headerAfter!.width).toBe(headerBefore!.width);
      await page.screenshot({ path: testInfo.outputPath('trend-dialog.png') });
      await canvas.hover({ position: { x: 90, y: 80 } });
      await expect(dialog.getByText('Alpha Rank', { exact: true })).toBeVisible();
      await dialog.getByTestId('trend-path-detail').scrollIntoViewIfNeeded();
      await expect(dialog.getByTestId('trend-alpha-contributions')).toContainText('32.0 分');
      await page.screenshot({ path: testInfo.outputPath('trend-alpha-v2.png') });
      await dialog.getByTestId('trend-history').last().scrollIntoViewIfNeeded();
      await expect(dialog.getByTestId('trend-history').last()).toContainText('排名 #63');
      await page.keyboard.press('Escape');
      await expect(dialog).not.toBeVisible();
      await expect(page.getByTestId('trend-row').first()).toBeVisible();
      expect(await page.locator('body').evaluate(el => ({ overflow: el.style.overflow, paddingRight: el.style.paddingRight }))).toEqual(before);
      await expect(page.getByRole('columnheader', { name: 'Path Score' })).toBeVisible();
      await page.getByTestId('trend-row').first().click();
      await expect(dialog).toBeVisible();
      await dialog.getByRole('button', { name: 'Close', exact: true }).click();
      await expect(dialog).not.toBeVisible();
      expect(errors).toEqual([]);
    });
  }
}

test('full universe has no pagination and remains sortable', async ({ page }) => {
  let rankingStarted = 0;
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: object = {};
    if (path.endsWith('/auth/status')) body = { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } };
    if (path.endsWith('/breadth-history')) body = { points: [], dates: [], officialCount: 0, warnings: [] };
    if (path.endsWith('/transitions')) body = { days: 3, items: [], warnings: [] };
    if (path.endsWith('/dates')) body = { items: [snapshot.tradeDate] };
    if (path.endsWith('/preview/status') || path.endsWith('/preview')) { await route.fulfill({ status: 404, json: {} }); return; }
    if (path.endsWith('/ranking')) {
      const states = ['IDLE', 'WATCHING', 'CANDIDATE', 'TRENDING', 'WEAKENING', 'BROKEN'];
      body = { ...summary, items: Array.from({ length: 3800 }, (_, rank) => ({
        ...snapshot, code: `TEST${rank}`, name: `Stock ${rank}`, rank: rank + 1,
        alphaScore: rank / 38, state: states[rank % states.length],
      })), candidates: [] };
      rankingStarted = Date.now();
    }
    await route.fulfill({ json: body });
  });
  await page.goto('/research/trend-following');
  await expect(page.getByTestId('trend-row')).toHaveCount(28);
  await expect(page.getByTestId('trend-ranking-count')).toContainText('3800');
  const scroll = page.getByTestId('trend-ranking-scroll');
  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => scroll.evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
    expect(await scroll.evaluate(el => el.getBoundingClientRect().right)).toBeLessThanOrEqual(width);
    const name = page.getByTestId('trend-row').first().locator('[data-column="name"]');
    const before = (await name.boundingBox())!;
    await scroll.evaluate(el => { el.scrollLeft = 1500; });
    const after = (await name.boundingBox())!;
    const viewport = (await scroll.boundingBox())!;
    expect(after.x).toBeGreaterThanOrEqual(viewport.x - 1);
    expect(after.x).toBeLessThan(before.x);
    await scroll.evaluate(el => { el.scrollLeft = 0; });
  }
  await scroll.evaluate(el => { el.scrollTop = el.scrollHeight; });
  await expect(page.getByTestId('trend-row').last()).toContainText('TEST3799');
  await scroll.evaluate(el => { el.scrollTop = 0; });
  console.log('full-universe render milliseconds', Date.now() - rankingStarted);
  await expect(page.getByRole('button', { name: '下一页' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Alpha Score', exact: true }).click();
  await expect(page.getByTestId('trend-row').first()).toContainText('TEST3799');
  await page.getByTestId('trend-ranking-search').fill('test2700');
  await expect(page.getByTestId('trend-row')).toHaveCount(1);
  await expect(page.getByTestId('trend-row')).toContainText('TEST2700');
  await page.getByTestId('trend-ranking-search').fill('Stock 1800');
  await expect(page.getByTestId('trend-row')).toHaveCount(1);
  await expect(page.getByTestId('trend-row')).toContainText('TEST1800');
  await page.getByTestId('trend-ranking-search').fill('');
  await page.getByTestId('trend-state-filter').getByRole('button', { name: '趋势健康', exact: true }).click();
  await expect(page.getByTestId('trend-ranking-count')).toContainText('633 / 3800');
  await expect(page.getByTestId('trend-row')).toHaveCount(28);
  await expect(page.getByTestId('trend-row').first()).toContainText('TEST3795');
  await expect(page.getByTestId('trend-row').first()).toContainText('趋势健康');
});
