import { expect, test } from '@playwright/test';

const assets = ['SPY', 'QQQ', 'TLT', 'UUP', 'USO', 'GLD', 'HYG', 'LQD', 'IWM', 'SMH', 'XLY', 'XLP', 'VIX'];
const ratios = ['HYG_LQD', 'IWM_SPY', 'SMH_SPY', 'XLY_XLP'];
const quality = { expected: 13, available: 11, coverage: 11 / 13, missing_symbols: ['UUP.US'], stale_symbols: ['VIX.US'], insufficient_history_symbols: ['TLT.US'], partial: true };
const metrics = { trade_date: '2026-09-11', ret_1d: 0.0011, ret_5d: -0.0146, ret_20d: 0.018, trend: 'UP' };
for (const width of [1280, 1440, 1920]) {
  for (const theme of ['light', 'dark', 'system']) {
    test(`macro at ${width}px in ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.emulateMedia({ colorScheme: 'dark' });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/api/v1/**', async route => {
        const url = new URL(route.request().url());
        if (url.pathname === '/api/v1/auth/status') return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
        if (url.pathname === '/api/v1/macro/dashboard') return route.fulfill({ json: {
          trade_date: '2026-09-11', generated_at: '2026-09-12T00:00:00Z', regime: 'RISK_ON', risk_score: 72, signal_coverage: 0.85,
          states: { rates: 'EASING', credit: 'HEALTHY', dollar: 'STRONG', volatility: 'CALM' }, data_quality: quality,
          signals: [{ key: 'VIX.US', risk_on_trend: 'DOWN', trend: 'DOWN', weight: 20, contribution: null }],
          instruments: assets.map((s, i) => ({ ...metrics, code: `${s}.US`, name: s, category: ['EQUITY', 'RATES', 'CREDIT'][i % 3], close: 80.87 + i })),
          ratios: ratios.map(key => ({ ...metrics, key, name: key.replace('_', ' / '), value: 0.754, signal: null, partial: true })),
        } });
        if (url.pathname === '/api/v1/macro/series') {
          const keys = (url.searchParams.get('symbols') || url.searchParams.get('series') || '').split(',');
          return route.fulfill({ json: { range: url.searchParams.get('range'), mode: url.searchParams.get('mode'), benchmark: url.searchParams.get('benchmark'), trade_date: '2026-09-11', data_quality: quality,
            series: keys.map((key, i) => ({ key, code: key.endsWith('.US') ? key : null, name: key, category: 'EQUITY', partial: i === 2,
              points: Array.from({ length: 20 }, (_, d) => ({ date: new Date(Date.UTC(2026, 7, 23 + d)).toISOString().slice(0, 10), value: 100 + (d * (i - 2) / 8) + Math.sin(d) })) })),
          } });
        }
        return route.fulfill({ json: {} });
      });
      await page.goto('/research/macro');
      await expect(page.getByRole('heading', { name: '宏观', exact: true })).toBeVisible();
      await expect(page.getByTestId('module-tabs').getByRole('tab', { name: '宏观', exact: true })).toHaveAttribute('data-state', 'active');
      await expect(page.getByTestId('macro-risk-score')).toContainText('72 / 100');
      await expect(page.locator('canvas')).toHaveCount(2);
      await expect.poll(() => page.getByTestId('macro-states').evaluate(el => getComputedStyle(el).gridTemplateColumns.split(' ').length)).toBe(width >= 1400 ? 6 : 3);
      await expect.poll(() => page.locator('canvas').first().evaluate(el => Math.abs(el.getBoundingClientRect().width - el.closest('[aria-busy]')!.getBoundingClientRect().width))).toBeLessThan(2);
      await expect(page.getByTestId('macro-instrument-table').locator('tbody tr')).toHaveCount(13);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.getByTestId('macro-signal-details').click();
      await expect(page.getByRole('dialog')).toContainText('N/A / 20');
      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog')).not.toBeVisible();
      await page.getByTestId('macro-performance-chart').getByTestId('macro-mode').selectOption('relative');
      await expect(page.getByTestId('macro-performance-chart').locator('[aria-busy]')).toHaveAttribute('aria-busy', 'false');
      await expect.poll(() => page.locator('canvas').first().evaluate(el => Math.abs(el.width / devicePixelRatio - el.getBoundingClientRect().width))).toBeLessThan(2);
      expect(errors).toEqual([]);
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      await page.screenshot({ path: testInfo.outputPath(`macro-${width}-${theme}.png`), fullPage: true });
    });
  }
}
