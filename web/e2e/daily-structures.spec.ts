import { expect, test } from '@playwright/test';
import { box } from '../src/utils/__tests__/fixtures/dailyStructures';
import { candle, dated } from '../src/utils/__tests__/fixtures/dailyPatterns';

for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  test(`structure markers stay compact and boundaries can be toggled at ${width}px`, async ({ page }, testInfo) => {
    const theme = width % 2 === 0 && width < 1024 ? 'dark' : 'light';
    const items = dated([...box(), candle(106, 108)]);
    const tradeDate = items.at(-1)!.tradeDate;
    const snapshot = { market: 'CN', code: '510300.SH', name: '沪深300ETF', tradeDate,
      category: '宽基', theme: '沪深300', riskGroup: 'CN_EQUITY', enabled: true, rank: 1,
      action: 'BUY', state: 'TRENDING', compositeScore: 85, referencePrice: 108,
      ma10Ratio: 0.03, ma20Ratio: 0.05, rs5D: 0.02, rs10D: 0.04, rs20D: 0.06, scoreComponents: {}, diagnostics: {} };
    await page.clock.setFixedTime(new Date('2026-11-14T04:00:00Z'));
    await page.setViewportSize({ width, height: 1100 });
    await page.addInitScript(value => localStorage.setItem('theme', value), theme);
    await page.addInitScript(() => {
      const original = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function (text, x, y, maxWidth) {
        if (text === '◆') {
          const transform = this.getTransform();
          this.canvas.dataset.structureX = String((transform.a * (x + this.measureText(text).width / 2) + transform.e) / this.canvas.width);
          this.canvas.dataset.structureY = String((transform.d * (y + 5) + transform.f) / this.canvas.height);
          this.canvas.dataset.structureFont = this.font;
        }
        original.call(this, text, x, y, maxWidth);
      };
    });
    let requests = 0;
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let body: object = {};
      if (path.endsWith('/auth/status')) body = { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } };
      else if (path.endsWith('/classification')) body = { code: snapshot.code, market: 'CN', memberships: { indices: [], industries: [] } };
      else if (path.endsWith('/preview') || path.endsWith('/preview/status')) return route.fulfill({ status: 404, json: {} });
      else if (path.endsWith('/rank-history')) body = { market: 'CN', dates: [tradeDate], officialCount: 1, series: [], previewDate: null };
      else if (path.endsWith('/forward-returns')) body = { items: [] };
      else if (path.endsWith('/dates')) body = { market: 'CN', latest: tradeDate, items: [tradeDate] };
      else if (path.endsWith('/ranking') || path.endsWith('/candidates')) body = { market: 'CN', tradeDate,
        universeSize: 1, dataReadyCount: 1, dataCoverage: 1, rankableSize: 1, rankableCoverage: 1, warnings: [], marketSnapshot: null, items: [snapshot] };
      else if (path.includes('/daily-bars/')) {
        requests++; body = { symbol: snapshot.code, market: 'CN', interval: '1d', adjustment: 'forward', items };
      } else if (path.endsWith('/etf-rotation/510300.SH')) body = { market: 'CN', metadata: snapshot, latest: snapshot, history: [snapshot], marketSnapshot: null };
      await route.fulfill({ json: body });
    });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/research/etf-rotation');
    await page.getByTestId('etf-ranking-row').click();
    const daily = page.getByTestId('daily-kline-card');
    await daily.scrollIntoViewIfNeeded();
    const summary = daily.getByTestId('daily-structure-summary');
    await expect(summary).toContainText('箱体向上突破');
    const canvas = daily.locator('canvas[data-structure-x]').first();
    await expect(canvas).toBeAttached();
    expect(await canvas.getAttribute('data-structure-font')).toContain('10px');
    const bounds = (await canvas.boundingBox())!;
    const x = Number(await canvas.getAttribute('data-structure-x')) * bounds.width;
    const y = Number(await canvas.getAttribute('data-structure-y')) * bounds.height;
    await page.mouse.move(bounds.x + x, bounds.y + y);
    await expect(daily.getByTestId('daily-structure-detail')).toContainText('结构确认');
    await expect(summary.getByRole('button', { name: '隐藏边界' })).toHaveCount(0);
    await page.mouse.click(bounds.x + x, bounds.y + y);
    await expect(summary.getByRole('button', { name: '隐藏边界' })).toBeVisible();
    await daily.screenshot({ path: testInfo.outputPath(`structures-selected-${width}.png`) });
    await summary.getByRole('button', { name: '隐藏边界' }).click();
    await expect(summary.getByRole('button', { name: '隐藏边界' })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(requests).toBe(1);
    expect(errors).toEqual([]);
    await daily.screenshot({ path: testInfo.outputPath(`structures-${width}.png`) });
  });
}
