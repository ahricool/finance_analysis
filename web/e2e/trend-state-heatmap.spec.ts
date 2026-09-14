import { expect, test } from '@playwright/test';

const states = ['IDLE', 'WATCHING', 'CANDIDATE', 'ENTRY', 'PYRAMIDING', 'HOLDING', 'WEAKENING', 'REDUCE', 'EXIT'];
const dates = Array.from({ length: 46 }, (_, i) => new Date(Date.UTC(2026, 6, 14 + i)))
  .filter(day => day.getUTCDay() !== 0 && day.getUTCDay() !== 6).slice(-30).map(day => day.toISOString().slice(0, 10));
const snapshots = Array.from({ length: 50 }, (_, i) => ({
  market: 'CN', code: `${String(i + 1).padStart(6, '0')}.SZ`, name: `趋势股票 ${i + 1}`,
  tradeDate: dates[29], rank: i + 1, state: 'HOLDING', action: 'HOLD', alphaScore: 86.3,
  trendScore: 82.6, rsScore: 79.4, fragilityScore: 18.5, trendDurationDays: 14,
  features: {}, scoreBreakdown: {}, fragilityBreakdown: {}, reasons: [], referencePrice: 110,
}));
const summary = { market: 'CN', tradeDate: dates[29], marketRegime: 'RISK_ON', marketScore: 82,
  suggestedMaxExposure: 0.8, universeSize: 3800, dataReadyCount: 3700, dataCoverage: 0.98,
  rankableCount: 3700, candidateCount: 50, entryCount: 1, warnings: [], features: {},
};
const heatmap = { market: 'CN', anchorDate: dates[29], dates, officialCount: 30, previewDate: null,
  previewTime: null, generatedAt: '2026-08-28T10:50:00Z', warnings: [],
  items: snapshots.map((stock, y) => ({ code: stock.code, name: stock.name, currentRank: stock.rank,
    history: dates.map((_, x) => x === 4 && y === 0 ? null : ({
      ...stock, state: states[y % 2 ? (x + y) % 9 : Math.min(8, Math.floor(x / 5))],
    })),
  })),
};

for (const width of [1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`state heatmap scroll and detail at ${width} ${theme}`, async ({ page }, testInfo) => {
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
        } else if (path.endsWith('/state-history')) {
          if (fail) { await route.fulfill({ status: 503, json: { detail: 'State history unavailable' } }); return; }
          expect(url.searchParams.get('limit')).toBe('50');
          body = heatmap;
        } else if (path.endsWith('/dates')) body = { market: 'CN', latest: dates[29], items: [...dates].reverse() };
        else if (path.endsWith('/ranking')) body = { ...summary, items: snapshots, candidates: [],
          portfolio: { ...summary, positions: [], maxExposure: 0.8, currentExposure: 0, positionCount: 0 } };
        else {
          const code = decodeURIComponent(path.split('/').pop()!);
          const stock = snapshots.find(item => item.code === code);
          if (stock) {
            requestedDetails.push(code);
            expect(url.searchParams.get('trade_date')).toBe(dates[29]);
            body = { market: 'CN', metadata: stock, latest: stock, marketContext: summary,
              history: dates.map(tradeDate => ({ ...stock, tradeDate })) };
          }
        }
        await route.fulfill({ json: body });
      });
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto('/research/trend-following');
      const panel = page.getByTestId('trend-state-heatmap');
      const canvas = panel.locator('canvas');
      await expect(canvas).toHaveCount(1);
      await panel.scrollIntoViewIfNeeded();
      expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
      const box = (await canvas.boundingBox())!;
      expect(box.height).toBe(600);
      // First visible cell, using the chart's fixed grid margins.
      let point = { x: box.x + 210 + (box.width - 252) / 60, y: box.y + 58 };
      await page.mouse.move(point.x, point.y);
      await panel.screenshot({ path: testInfo.outputPath(`heatmap-${theme}-${width}.png`) });
      await page.mouse.move(point.x, point.y);
      await page.waitForTimeout(150);
      await page.screenshot({ path: testInfo.outputPath('heatmap-tooltip.png') });
      await page.mouse.click(point.x, point.y);
      await expect(page.getByTestId('trend-detail')).toBeVisible();
      await expect(page.getByTestId('trend-rank-history')).toBeVisible();
      await expect(page.getByTestId('trend-fragility-history')).toBeVisible();
      expect(requestedDetails[0]).toBe(snapshots[0]!.code);
      await page.keyboard.press('Escape');
      await expect(page.getByTestId('trend-detail')).not.toBeVisible();
      await panel.scrollIntoViewIfNeeded();
      await page.mouse.move(point.x, point.y);
      const scrolledBox = (await canvas.boundingBox())!;
      point = { x: scrolledBox.x + 210 + (scrolledBox.width - 252) / 60, y: scrolledBox.y + 58 };
      await page.mouse.move(point.x, point.y);
      for (let index = 0; index < 6; index++) {
        await page.mouse.wheel(0, 1200);
        await page.waitForTimeout(80);
      }
      // Jump to the final window through the scrollbar after verifying wheel interaction.
      await page.mouse.click(scrolledBox.x + scrolledBox.width - 11, scrolledBox.y + 574);
      await page.waitForTimeout(200);
      await panel.screenshot({ path: testInfo.outputPath(`heatmap-scrolled-${theme}-${width}.png`) });
      await page.mouse.click(point.x, point.y);
      await expect(page.getByTestId('trend-detail')).toBeVisible();
      expect(requestedDetails.at(-1)).toBe(snapshots[30]!.code);
      await page.keyboard.press('Escape');
      await expect(page.getByTestId('trend-detail')).not.toBeVisible();
      await panel.scrollIntoViewIfNeeded();
      const lastBox = (await canvas.boundingBox())!;
      // The final visible row is #50. Stock labels must remain clickable after zoom filtering.
      await page.mouse.click(lastBox.x + 160, lastBox.y + 566);
      await expect(page.getByTestId('trend-detail')).toBeVisible();
      expect(requestedDetails.at(-1)).toBe(snapshots[49]!.code);
      await page.keyboard.press('Escape');
      fail = true;
      await page.getByRole('button', { name: '刷新', exact: true }).click();
      await expect(panel.getByRole('button', { name: '重试状态历史' })).toBeVisible();
      await expect(page.getByTestId('trend-row')).toHaveCount(50);
      expect(errors).toEqual([]);
    });
  }
}

test('preview column is explicit and same-day official history opens the official detail', async ({ page }, testInfo) => {
  const previewDate = '2026-08-31';
  let officialToday = false;
  const previewSnapshots = snapshots.map(stock => ({ ...stock, tradeDate: previewDate, state: 'WEAKENING' }));
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let body: object = {};
    if (path === '/api/v1/auth/status') body = { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } };
    else if (path.endsWith('/state-history')) {
      if (url.searchParams.get('include_preview') !== 'true') {
        await route.fulfill({ json: heatmap }); return;
      }
      body = { ...heatmap, anchorDate: previewDate,
        dates: officialToday ? [...dates.slice(1), previewDate] : [...dates, previewDate],
        previewDate: officialToday ? null : previewDate, previewTime: officialToday ? null : '2026-08-31T06:35:00Z',
        items: heatmap.items.map((stock, i) => ({ ...stock,
          history: [...(officialToday ? stock.history.slice(1) : stock.history), previewSnapshots[i]],
        })),
      };
    } else if (path.endsWith('/preview/status') || path.endsWith('/preview')) {
      body = { ...summary, status: 'completed', tradeDate: previewDate, previewTime: '2026-08-31T06:35:00Z',
        snapshots: previewSnapshots, snapshotCount: 50, scoreBreakdown: {},
      };
    } else if (path.endsWith('/ranking')) body = { ...summary, items: snapshots, candidates: [],
      portfolio: { positions: [], maxExposure: 0.8, currentExposure: 0, positionCount: 0 } };
    else if (path.endsWith('/dates')) body = { market: 'CN', latest: dates[29], items: [...dates].reverse() };
    else if (path.endsWith('/000001.SZ')) {
      expect(url.searchParams.get('trade_date')).toBe(previewDate);
      body = { market: 'CN', metadata: snapshots[0], latest: snapshots[0], marketContext: summary,
        history: dates.map(tradeDate => ({ ...snapshots[0], tradeDate })) };
    }
    await route.fulfill({ json: body });
  });
  await page.goto('/research/trend-following');
  await expect(page.getByTestId('research-mode-preview')).toHaveAttribute('aria-pressed', 'true');
  const panel = page.getByTestId('trend-state-heatmap');
  await expect(panel).toContainText('P 列为当天预演');
  await expect(panel.locator('canvas')).toHaveCount(1);
  await panel.screenshot({ path: testInfo.outputPath('heatmap-preview.png') });
  officialToday = true;
  await page.getByTestId('trend-refresh').click();
  await expect(panel).not.toContainText('P 列为当天预演');
  await expect(panel.locator('canvas')).toHaveCount(1);
  await panel.scrollIntoViewIfNeeded();
  const box = (await panel.locator('canvas').boundingBox())!;
  await page.mouse.click(box.x + 220, box.y + 58);
  await expect(page.getByTestId('trend-detail')).toBeVisible();
  await expect(page.getByTestId('trend-rank-history')).toBeVisible();
});
