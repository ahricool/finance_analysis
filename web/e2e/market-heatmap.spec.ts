import { expect, test } from '@playwright/test';
import { dashboardResponse } from '../tests/fixtures/dashboard';

for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`market heatmap ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        if (url.pathname === '/api/v1/market-heatmap') {
          const market = url.searchParams.get('market') ?? 'CN';
          const groups = market === 'CN' ? ['银行', '电子', '食品饮料', '医药生物', '汽车', '电力设备'] : ['科技', '金融服务', '医疗健康', '可选消费', '能源', '工业'];
          return route.fulfill({ json: { status: 'ready', snapshot: {
            market, source: market === 'CN' ? 'easyquotation' : 'yfinance', generated_at: '2026-10-23T02:00:00Z',
            data_as_of: '2026-10-23T01:59:00Z', data_latest_at: '2026-10-23T02:00:00Z',
            classification_observed_at: '2026-10-18T02:00:00Z', min_market_cap: market === 'CN' ? 1e10 : 2e9,
            refresh_seconds: 900, excluded_count: 0, unclassified_count: 0,
            items: Array.from({ length: 120 }, (_, i) => ({
              code: market === 'CN' ? `${600000 + i}.SH` : `STOCK${i}.US`, name: market === 'CN' ? ['贵州茅台', '宁德时代', '招商银行', '中际旭创'][i % 4] : ['NVIDIA', 'Apple', 'Microsoft', 'JPMorgan'][i % 4],
              market_cap: i === 0 ? 5e12 : 2e10 * (120 - i), price: 100, change_pct: (i % 11 - 5) * 0.8,
              group_code: `group${i % groups.length}`, group_name: groups[i % groups.length], quote_time: '2026-10-23T02:00:00Z',
            })),
          } } });
        }
        try { return route.fulfill({ json: dashboardResponse(url) }); }
        catch { return route.fulfill({ json: {} }); }
      });
      await page.goto('/market/heatmap');
      await expect(page.getByTestId('heatmap-chart').locator('canvas')).toBeVisible();
      await expect(page.getByTestId('heatmap-chart').locator('[data-ready="true"]')).toBeVisible();
      await expect(page.getByTestId('market-heatmap-page')).toContainText('120 只股票');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.getByTestId('heatmap-market-US').click();
      await expect(page.getByTestId('heatmap-market-US')).toHaveAttribute('aria-pressed', 'true');
      await expect(page.getByTestId('market-heatmap-page')).toContainText('Yahoo Finance');
      await expect(page.getByTestId('heatmap-chart').locator('canvas')).toBeVisible();
      await expect(page.getByTestId('heatmap-chart').locator('[data-ready="true"]')).toBeVisible();
      if (width === 390 || width === 1440) await page.screenshot({ path: testInfo.outputPath(`heatmap-${width}-${theme}.png`) });
      expect(errors).toEqual([]);
    });
  }
}
