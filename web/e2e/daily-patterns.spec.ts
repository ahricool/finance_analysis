import { expect, test } from '@playwright/test';
import { candle, dated, engulfing, hammer } from '../src/utils/__tests__/fixtures/dailyPatterns';

for (const theme of ['light', 'dark']) {
  test(`daily Price Action renders and marker clicks work in ${theme}`, async ({ page }, testInfo) => {
    const items = dated([...Array.from({ length: 60 }, () => candle(105, 105)), ...engulfing(), ...hammer()]);
    const highlightedDate = items[67]!.tradeDate;
    const snapshot = { market: 'CN', code: '510300.SH', name: '沪深300ETF', tradeDate: highlightedDate,
      category: '宽基', theme: '沪深300', riskGroup: 'CN_EQUITY', enabled: true, rank: 1,
      action: 'BUY', state: 'TRENDING', compositeScore: 85, referencePrice: 100,
      ma10Ratio: 0.03, ma20Ratio: 0.05, rs5D: 0.02, rs10D: 0.04, rs20D: 0.06, scoreComponents: {}, diagnostics: {} };
    await page.clock.setFixedTime(new Date('2026-11-14T04:00:00Z'));
    await page.setViewportSize({ width: theme === 'light' ? 1280 : 1920, height: 1100 });
    await page.addInitScript(value => localStorage.setItem('theme', value), theme);
    await page.addInitScript(() => {
      const original = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function (text, x, y, maxWidth) {
        if (text.startsWith('↑ 吞没')) {
          const transform = this.getTransform();
          this.canvas.dataset.patternX = String((transform.a * x + transform.e) / this.canvas.width);
          this.canvas.dataset.patternY = String((transform.d * y + transform.f) / this.canvas.height);
        }
        if (text.startsWith('查看日 ')) this.canvas.dataset.researchMarker = 'true';
        original.call(this, text, x, y, maxWidth);
      };
    });
    let dailyRequests = 0;
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let body: object = {};
      if (path.endsWith('/auth/status')) body = { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } };
      else if (path.endsWith('/preview') || path.endsWith('/preview/status')) return route.fulfill({ status: 404, json: {} });
      else if (path.endsWith('/rank-history')) body = { market: 'CN', dates: [highlightedDate], officialCount: 1, series: [], previewDate: null };
      else if (path.endsWith('/forward-returns')) body = { items: [] };
      else if (path.endsWith('/dates')) body = { market: 'CN', latest: highlightedDate, items: [highlightedDate] };
      else if (path.endsWith('/ranking') || path.endsWith('/candidates')) body = { market: 'CN', tradeDate: highlightedDate,
        universeSize: 1, dataReadyCount: 1, dataCoverage: 1, rankableSize: 1, rankableCoverage: 1, warnings: [], marketSnapshot: null, items: [snapshot] };
      else if (path.includes('/daily-bars/')) {
        dailyRequests++;
        body = { symbol: snapshot.code, market: 'CN', interval: '1d', adjustment: 'forward', items };
      } else if (path.endsWith('/etf-rotation/510300.SH')) body = { market: 'CN', metadata: snapshot, latest: snapshot, history: [snapshot], marketSnapshot: null };
      await route.fulfill({ json: body });
    });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/research/etf-rotation');
    await page.getByTestId('etf-ranking-row').click();
    const daily = page.getByTestId('daily-kline-card');
    await daily.scrollIntoViewIfNeeded();
    const detail = daily.getByTestId('daily-pattern-detail');
    await expect(detail).toContainText('锤子线');
    await expect(daily.locator('canvas[data-research-marker]').first()).toBeAttached();
    const canvas = daily.locator('canvas[data-pattern-x]').first();
    await expect(canvas).toBeAttached();
    const box = (await canvas.boundingBox())!;
    const x = Number(await canvas.getAttribute('data-pattern-x')) * box.width;
    const y = Number(await canvas.getAttribute('data-pattern-y')) * box.height;
    await page.mouse.click(box.x + x, box.y + y);
    await expect(detail).toContainText('看涨吞没');
    await expect(detail).toContainText('阳线实体完整吞没');
    expect(dailyRequests).toBe(1);
    expect(errors).toEqual([]);
    await daily.screenshot({ path: testInfo.outputPath(`daily-patterns-${theme}.png`) });
  });
}
