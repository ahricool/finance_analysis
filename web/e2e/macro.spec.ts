import { expect, test } from '@playwright/test';

const assets = ['SPY', 'QQQ', 'TLT', 'UUP', 'USO', 'GLD', 'HYG', 'LQD', 'IWM', 'SMH', 'XLY', 'XLP', 'VIX'];
const names = ['S&P 500', 'Nasdaq 100', 'Long Treasury', 'US Dollar', 'Crude Oil', 'Gold', 'High Yield Credit', 'Investment Grade Credit', 'Russell 2000', 'Semiconductor', 'Consumer Discretionary', 'Consumer Staples', 'VIX'];
const dates = Array.from({ length: 30 }, (_, d) => new Date(Date.UTC(2026, 7, 13 + d))).filter(d => ![0, 6].includes(d.getUTCDay())).slice(-20).map(d => d.toISOString().slice(0, 10));
const ratios = ['HYG_LQD', 'IWM_SPY', 'SMH_SPY', 'XLY_XLP'];
const quality = { expected: 13, available: 11, coverage: 11 / 13, missing_symbols: ['UUP.US'], stale_symbols: ['VIX.US'], insufficient_history_symbols: ['TLT.US'], partial: true };
const metrics = { trade_date: '2026-09-11', ret_1d: 0.0011, ret_5d: -0.0146, ret_20d: 0.018, trend: 'UP' };
for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
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
          instruments: assets.map((s, i) => ({ ...metrics, code: `${s}.US`, name: names[i], category: ['EQUITY', 'RATES', 'CREDIT'][i % 3], close: 80.87 + i })),
          ratios: ratios.map(key => ({ ...metrics, key, name: key.replace('_', ' / '), value: 0.754, signal: null, partial: true })),
        } });
        if (url.pathname === '/api/v1/macro/series') {
          const keys = (url.searchParams.get('symbols') || url.searchParams.get('series') || '').split(',');
          return route.fulfill({ json: { range: url.searchParams.get('range'), mode: url.searchParams.get('mode'), benchmark: url.searchParams.get('benchmark'), trade_date: '2026-09-11', dates, data_quality: quality,
            series: keys.map((key, i) => ({ key, code: key.endsWith('.US') ? key : null, name: key.endsWith('.US') ? names[assets.indexOf(key.replace('.US', ''))] : key, category: 'EQUITY', partial: i === 2,
              points: dates.flatMap((date, d) => i === 2 && [5, 6, 12].includes(d) ? [] : [{ date, value: 100 + (d * (i - 2) / 8) + Math.sin(d) }]) })),
          } });
        }
        if (url.pathname.includes('/market-data/daily-bars/')) {
          const code = decodeURIComponent(url.pathname.split('/').at(-1)!);
          expect(url.searchParams.get('start_date')).toMatch(/^\d{4}-\d{2}-\d{2}$/);
          expect(url.searchParams.get('end_date')).toBeNull();
          return route.fulfill({ json: { symbol: code, market: 'US', interval: '1d', adjustment: 'forward', source: 'database',
            items: dates.map((date, i) => ({ trade_date: date, open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i, volume: 100000, amount: null })),
          } });
        }
        if (url.pathname.endsWith('/quote')) {
          const code = url.pathname.split('/').at(-2)!;
          return route.fulfill({ json: { stock_code: code, current_price: 120,
            open: 119, high: 121, low: 118, prev_close: 119, volume: 100000, amount: 12000000,
          } });
        }
        if (url.pathname.endsWith('/classification')) return route.fulfill({ json: { code: url.pathname.split('/').at(-2), memberships: { indices: [] } } });
        return route.fulfill({ status: 404, json: { detail: 'No research snapshot' } });
      });
      await page.goto('/research/macro');
      await expect(page.getByRole('heading', { name: '宏观数据', exact: true })).toBeVisible();
      await expect(page.getByTestId('macro-page')).toBeVisible();
      await expect(page.getByTestId('macro-risk-score')).toContainText('72 / 100');
      await expect(page.locator('canvas')).toHaveCount(2);
      await expect.poll(() => page.getByTestId('macro-states').evaluate(el => getComputedStyle(el).gridTemplateColumns.split(' ').length)).toBe(width >= 1400 ? 6 : width >= 1024 ? 3 : 2);
      await expect.poll(() => page.locator('canvas').first().evaluate(el => Math.abs(el.getBoundingClientRect().width - el.closest('[aria-busy]')!.getBoundingClientRect().width))).toBeLessThan(2);
      await expect(page.getByTestId('macro-instrument-table').locator('tbody tr')).toHaveCount(13);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      const legend = page.getByTestId('macro-performance-chart').getByTestId('macro-legend');
      await expect(legend.getByRole('button')).toHaveCount(13);
      await expect(legend).toContainText('TLT.US · Long Treasury');
      await expect(legend).not.toContainText('数据不完整');
      await page.getByTestId('macro-legend-TLT.US').click();
      await expect(page.getByTestId('macro-legend-TLT.US')).toHaveAttribute('aria-pressed', 'false');
      await page.getByTestId('macro-legend-TLT.US').click();
      await expect(page.getByTestId('macro-legend-TLT.US')).toHaveAttribute('aria-pressed', 'true');
      await page.getByTestId('macro-signal-details').click();
      const signals = page.getByRole('dialog', { name: 'Risk Score 构成', exact: true });
      await expect(signals).toContainText('N/A / 20');
      await signals.getByRole('button', { name: 'Close', exact: true }).click();
      await expect(signals).not.toBeVisible();
      await page.getByTestId('macro-performance-chart').getByTestId('macro-mode').selectOption('relative');
      await expect(page.getByTestId('macro-performance-chart').locator('[aria-busy]')).toHaveAttribute('aria-busy', 'false');
      await expect.poll(() => page.locator('canvas').first().evaluate(el => Math.abs(el.width / devicePixelRatio - el.getBoundingClientRect().width))).toBeLessThan(2);
      // Verify both an ETF and the VIX index use the existing stock detail/K-line flow.
      for (const code of ['SPY', 'VIX']) {
        await page.getByRole('button', { name: `查看 ${code}.US ${names[assets.indexOf(code)]} 详情`, exact: true }).click();
        const dialog = page.getByRole('dialog');
        await expect(dialog).toContainText(`${code}.US`);
        await expect(dialog.getByRole('tab', { name: '行情', exact: true })).toHaveAttribute('data-state', 'active');
        await expect(dialog.getByTestId('kline-coverage')).toContainText('20 根日 K');
        await dialog.getByTestId('kline-period-1M').click();
        await expect(dialog.getByTestId('kline-coverage')).toContainText('根月 K');
        await expect(dialog).toContainText('120');
        await page.keyboard.press('Escape');
        await expect(dialog).not.toBeVisible();
      }
      expect(errors).toEqual([]);
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      await page.screenshot({ path: testInfo.outputPath(`macro-${width}-${theme}.png`), fullPage: true });
    });
  }
}
