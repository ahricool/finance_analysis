import { expect, test } from '@playwright/test';

const snapshot = {
  market: 'CN', code: '000001.SZ', name: '平安银行', tradeDate: '2026-08-28',
  rank: 12, rankChange1D: 5, rankChange3D: -2, rankChange5D: 0,
  state: 'TRENDING', setup: 'BREAKOUT_20D', alphaScore: 82.5,
  trendScore: 80, rsScore: 78, breakoutScore: 80, referencePrice: 25, atr: .5,
  trendDurationDays: 13, trendLifecycle: 'EXPANSION', fragilityScore: 18,
  fragilityBreakdown: { accelerationDecay: 12, qualityDecay: 15, efficiencyDecay: 20, relativeStrengthDecay: 18, rankDecay: 24, priceStructureRisk: 15 },
  features: { mrState: 'MR_REBOUND', mrQuality: 82, rsi14: 28, distanceFromMa20Atr: -2, boxState: 'BOX_READY', boxQuality: 88, boxWindowDays: 30, boxWidthPct: .084, atrPercent: .02, previousLow10: 24,
      riskSizing: { riskBudgetPct: .01, maxPositionPct: .25, atrMultiple: 2.5,
        atrStopPct: .05, structureStopPct: .04, stopLossPct: .05, stopPrice: 23.75,
        suggestedPositionPct: .20, stopBasis: 'ATR' },
    alphaVersion: 3, pathScore: 95, setupScore: 80, weightedR2: .98, weightedSlopePercentile: 92,
    positiveReturnConcentration: .3, atrExpansionRatio: 1.1, downsideControlQuality: 90, downsideUpsideRatio: .10536,
    trendQuality: 87, trendAcceleration: 0.12, signedEfficiencyRatio10D: 0.71, priorCompression: true,
    r2Quality: 98, momentumQuality: 74, return10DQuality: 72, return20DQuality: 70, drawdownQuality: 81,
    rs5DQuality: 55, rs10DQuality: 61, rs20DQuality: 58,
    breakoutQuality: 77, extensionQuality: 66, volumeQuality: 80, compressionQuality: 40,
    concentrationQuality: 88, volatilityQuality: 72,
    alphaTrendContribution: 32, alphaRsContribution: 19.5, alphaSetupContribution: 12, alphaPathContribution: 19 }, scoreBreakdown: { alpha: { version: 3,
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
        } else if (pathname.endsWith('/market-data/daily-bars/000001.SZ')) {
          expect(new URL(route.request().url()).searchParams.get('end_date')).toBeNull();
          body = { symbol: snapshot.code, items: ['2026-08-28', '2026-08-31'].map(tradeDate => ({
            tradeDate, open: 100, high: 110, low: 95, close: 105, volume: 100,
          })) };
        } else if (pathname.endsWith('/market-data/forward-returns')) {
          body = { items: [{ code: snapshot.code, forward_return_3d: .03, forward_return_5d: -.02, forward_return_10d: null, forward_return_20d: .08 }] };
        } else if (pathname.endsWith('/trend-following/event-study')) {
          const params = new URL(route.request().url()).searchParams;
          const market = params.get('market') || 'CN';
          const regime = params.get('regime') || 'ALL';
          const strategy = params.get('strategy') === 'ALL' ? 'BOX_BREAKOUT' : params.get('strategy');
          const coverage = { featureCoverage: .5, featureSnapshotCount: 1, snapshotCount: 2, status: 'insufficient_feature_history', earliestCompleteDate: '2026-08-28', incompleteDates: [] };
          body = { market, startDate: params.get('start_date'), endDate: params.get('end_date'), method: 'signal_close_v1', benchmark: market === 'US' ? 'SPY.US' : '510300.SH',
            snapshotDates: ['2026-08-28'], missingSnapshotDates: [], boxFeatureCoverage: coverage, mrFeatureCoverage: coverage,
            groups: ['TREND_FOLLOWING', 'BOX_BREAKOUT', 'PULLBACK_RESUME', 'MEAN_REVERSION'].map(key => ({
              ...coverage, strategy: key, regime, eventCount: 1, excursionCount: 1,
              horizons: [5, 10, 20].map(days => ({ days, maturedCount: 1, excessMaturedCount: 1, pendingCount: 0, missingCount: 0, meanReturn: .1, medianReturn: .1, winRate: 1, meanExcessReturn: .05, medianExcessReturn: .05, excessWinRate: 1 })),
              mfe20: { mean: .15, median: .15 }, mae20: { mean: -.03, median: -.03 },
            })), eventCount: 1, offset: 0, limit: 100,
            events: [{ market, tradeDate: '2026-08-28', code: '000001.SZ', name: '历史样本', strategy, regime: 'RISK_OFF', signalPrice: 100, evaluationBasePrice: 100,
              context: { boxQuality: 88, boxWindowDays: 30, boxWidthPct: .08, boxBreakoutDistanceAtr: .4 },
              horizons: [5, 10, 20].map(days => ({ days, status: 'available', value: .1, excessStatus: 'available', excessReturn: .05 })),
              excursionStatus: 'available', observedSessions: 20, missingDates: [], mfe20: .15, mae20: -.03 }],
          };
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
      await expect(page.getByTestId('trend-export-excel')).toBeEnabled();
      const downloadPromise = page.waitForEvent('download');
      await page.getByTestId('trend-export-excel').click();
      const download = await downloadPromise;
      expect(download.suggestedFilename()).toBe(`趋势分析_CN_${snapshot.tradeDate}_official.xlsx`);
      expect(await download.failure()).toBeNull();
      await download.saveAs(testInfo.outputPath('ranking.xlsx'));

      await page.getByTestId('trend-view-mr').click();
      await expect(page.getByTestId('trend-row').first()).toContainText('反弹确认');
      await page.getByTestId('trend-view-study').click();
      await expect(page.getByTestId('study-strategy-row')).toHaveCount(4);
      await expect(page.getByTestId('trend-event-study')).toContainText('insufficient_feature_history');
      await page.getByLabel('研究开始日期').fill('2026-06-01');
      await page.getByLabel('研究市场环境').selectOption('RISK_OFF');
      await page.getByTestId('study-strategy-row').filter({ hasText: '箱体突破' }).click();
      await expect(page.getByTestId('study-event-row')).toContainText('历史样本');
      await expect(page.getByTestId('study-event-row')).toContainText('Quality: 88.00');
      await page.getByRole('radio', { name: '美股', exact: true }).click();
      await expect(page.getByTestId('study-coverage')).toContainText('SPY.US');
      await page.getByRole('radio', { name: 'A股', exact: true }).click();
      await expect(page.getByTestId('study-coverage')).toContainText('510300.SH');
      await page.screenshot({ path: testInfo.outputPath('strategy-study.png') });
      await page.getByTestId('trend-view-box').click();
      await expect(page.getByTestId('trend-row').first()).toContainText('待突破');
      await expect(page.getByTestId('trend-row').first()).toContainText('30d');
      await expect(page.getByTestId('trend-row').first().locator('[data-column="forwardReturn20D"]')).toHaveText('8.0%');
      await page.getByTestId('trend-row').first().click();
      await expect(page.getByTestId('trend-box-structure')).toContainText('Box Structure');
      await page.keyboard.press('Escape');
      await page.getByTestId('trend-view-ranking').click();
      const row = page.getByTestId('trend-row').first();
      await expect(row.locator('[data-column="forwardReturn3D"]')).toHaveText('3.0%');
      await expect(row.locator('[data-column="forwardReturn5D"]')).toHaveText('-2.0%');
      await expect(row.locator('[data-column="forwardReturn10D"]')).toHaveText('—');
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
      await expect(dialog.getByTestId('trend-path-detail')).toContainText('Alpha V3');
      const risk = dialog.getByTestId('trend-risk-sizing');
      await expect(risk).toBeVisible();
      for (const text of ['建议仓位', '20.0%', '建议止损', '-5.0%', '止损价格', '23.75', '账户风险预算', '1.0%']) {
        await expect(risk).toContainText(text);
      }
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
      await page.screenshot({ path: testInfo.outputPath('trend-alpha-v3.png') });
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
  const headerTop = (await scroll.locator('thead').boundingBox())!.y;
  await scroll.evaluate(el => { el.scrollTop = el.scrollHeight; });
  expect(Math.abs((await scroll.locator('thead').boundingBox())!.y - headerTop)).toBeLessThan(1);
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

test('ranking row opens detail from keyboard and restores focus', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
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
    } else if (pathname.endsWith('/trend-following/ranking')) {
      body = { ...summary, items: [snapshot], candidates: [snapshot] };
    } else if (pathname.endsWith('/trend-following/000001.SZ')) {
      body = { market: 'CN', metadata: snapshot, latest: snapshot, history, marketContext: summary };
    }
    await route.fulfill({ json: body });
  });
  await page.goto('/research/trend-following');
  const row = page.getByTestId('trend-row').first();
  await row.focus();
  await expect(row).toBeFocused();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(row).toBeFocused();
  await page.keyboard.press('Space');
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(row).toBeFocused();
});
