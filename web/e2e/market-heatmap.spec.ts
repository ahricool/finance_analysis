import { expect, test } from '@playwright/test';
import { dashboardResponse } from '../tests/fixtures/dashboard';

for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`market heatmap ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      const errors: string[] = [];
      let snapshots = 0;
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith('/classification')) return route.fulfill({ json: { memberships: { industries: [], indices: [] } } });
        if (url.pathname.endsWith('/quote')) return route.fulfill({ status: 404, json: { detail: 'No quote' } });
        if (url.pathname.includes('/market-data/daily-bars/')) return route.fulfill({ json: { bars: [], warnings: [] } });
        if (url.pathname === '/api/v1/market-heatmap') {
          snapshots++;
          const market = url.searchParams.get('market') ?? 'CN';
          const groups = market === 'CN' ? ['银行', '电子', '食品饮料', '医药生物', '汽车', '电力设备'] : ['科技', '金融服务', '医疗健康', '可选消费', '能源', '工业'];
          return route.fulfill({ json: { status: 'ready', snapshot: {
            market, source: market === 'CN' ? 'easyquotation' : 'yfinance', generated_at: '2026-10-23T02:00:00Z',
            data_as_of: '2026-10-23T01:59:00Z', data_latest_at: '2026-10-23T02:00:00Z',
            classification_observed_at: '2026-10-18T02:00:00Z', min_market_cap: market === 'CN' ? 1e10 : 2e9,
            refresh_seconds: 900, excluded_count: 0, unclassified_count: 0,
            items: Array.from({ length: 120 }, (_, i) => ({
              code: market === 'CN' ? `${600000 + i}.SH` : `STOCK${i}.US`, name: market === 'CN' ? ['贵州茅台', '宁德时代', '招商银行', '中际旭创'][i % 4] : ['NVIDIA Corporation', 'Taiwan Semiconductor Manufacturing Company Limited', 'Microsoft Corporation', 'JPMorgan Chase & Co.'][i % 4],
              market_cap: i === 0 ? 5e12 : 2e10 * (120 - i), price: 100, change_pct: (i % 11 - 5) * 0.8,
              group_code: `group${i % groups.length}`, group_name: groups[i % groups.length], quote_time: '2026-10-23T02:00:00Z',
            })),
          } } });
        }
        try { return route.fulfill({ json: dashboardResponse(url) }); }
        catch { return route.fulfill({ json: {} }); }
      });
      await page.goto('/market/heatmap');
      await expect(page.getByTestId('heatmap-stock')).toHaveCount(120);
      await expect(page.getByTestId('market-heatmap-page')).toContainText('120 只股票');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.getByTestId('heatmap-market-US').click();
      await expect(page.getByTestId('heatmap-market-US')).toHaveAttribute('aria-pressed', 'true');
      await expect(page.getByTestId('market-heatmap-page')).toContainText('Yahoo Finance');
      await expect(page.getByTestId('heatmap-stock')).toHaveCount(120);
      const overflow = await page.getByTestId('heatmap-stock').evaluateAll(tiles => tiles.filter(tile => {
        const box = tile.getBoundingClientRect();
        return [...tile.querySelectorAll('span')].some(label => {
          if (getComputedStyle(label).visibility === 'hidden' || getComputedStyle(label).display === 'none') return false;
          const rect = label.getBoundingClientRect();
          return label.scrollWidth > label.clientWidth + 1 || rect.left < box.left || rect.right > box.right + 1 || rect.top < box.top || rect.bottom > box.bottom + 1;
        });
      }).map(tile => tile.getAttribute('data-code')));
      expect(overflow).toEqual([]);
      const labels = page.getByTestId('heatmap-stock-name');
      await expect(labels).toHaveCount(120);
      const sizes = await labels.evaluateAll(nodes => nodes.map(node => parseFloat(getComputedStyle(node).fontSize)));
      expect(sizes.every(size => size >= 5 && size <= 16)).toBe(true);
      expect(new Set(sizes).size).toBeGreaterThan(1);
      if (width === 390 && theme === 'light') {
        const tile = page.getByTestId('heatmap-stock').first();
        const original = await tile.evaluate(node => {
          const name = node.querySelector('[data-testid="heatmap-stock-name"]')!;
          const saved = { style: node.getAttribute('style')!, text: name.textContent! };
          name.textContent = 'AA';
          Object.assign((node as HTMLElement).style, { width: '14px', height: '10px' });
          return saved;
        });
        await expect.poll(() => tile.locator('.heatmap-labels').evaluate(node => getComputedStyle(node).fontSize)).toBe('5px');
        await expect(tile.getByTestId('heatmap-stock-name')).toBeVisible();
        await expect(tile.getByTestId('heatmap-stock-change')).toBeHidden();
        await tile.evaluate(node => Object.assign((node as HTMLElement).style, { width: '120px', height: '80px' }));
        await expect.poll(() => tile.locator('.heatmap-labels').evaluate(node => getComputedStyle(node).fontSize)).toBe('16px');
        await expect(tile.getByTestId('heatmap-stock-change')).toBeVisible();
        await tile.evaluate((node, saved) => {
          node.setAttribute('style', saved.style);
          node.querySelector('[data-testid="heatmap-stock-name"]')!.textContent = saved.text;
        }, original);
      }
      const first = page.getByTestId('heatmap-stock').first();
      await first.click();
      await expect(page.getByRole('dialog')).toHaveCount(1);
      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await first.focus();
      await page.keyboard.press('Space');
      await expect(page.getByRole('dialog')).toHaveCount(1);
      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await page.getByRole('combobox', { name: '筛选热力图行业' }).click();
      await page.getByRole('option', { name: '科技', exact: true }).click();
      await expect(page.getByTestId('heatmap-group')).toHaveCount(1);
      await expect(page.getByTestId('heatmap-stock')).toHaveCount(20);
      await page.getByTestId('heatmap-stock').last().scrollIntoViewIfNeeded();
      await page.getByRole('textbox', { name: '搜索热力图股票' }).fill('STOCK0.US');
      await expect(page.getByTestId('heatmap-stock')).toHaveCount(1);
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBeLessThan(500);
      await page.getByRole('button', { name: '重置筛选' }).click();
      await expect(page.getByTestId('heatmap-stock')).toHaveCount(120);
      expect(snapshots).toBe(2);
      await first.focus();
      await page.keyboard.press('Enter');
      await expect(page.getByRole('dialog')).toHaveCount(1);
      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog')).toHaveCount(0);
      if (width === 390 || width === 1440) await page.screenshot({ path: testInfo.outputPath(`heatmap-${width}-${theme}.png`) });
      expect(errors).toEqual([]);
    });
  }
}
