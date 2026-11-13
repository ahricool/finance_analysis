import { expect, test } from '@playwright/test';

const codes = 'SPY QQQ NVDA IWM TSLA MU AAPL AMD SPCX INTC AMZN IBIT CRWV TLT GOOGL META MSFT SOXL IREN GLD AVGO TQQQ MSTR SMH HYG SOFI SLV DRAM WULF SMCI'.split(' ');
const now = '2026-11-12T16:00:05Z';
for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  test(`intraday options sorting, stable live rows and minute panel at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1100 });
    await page.clock.setFixedTime(new Date(now));
    await page.addInitScript(dark => localStorage.setItem('theme', dark ? 'dark' : 'light'), width < 1280);
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    let changed = false;
    let chartRequests = 0;
    const items = codes.map((code, i) => ({ symbol: `${code}.US`, name: code === 'SPCX' ? null : `${code}观察标的`,
      last_price: code === 'SPCX' ? null : 100 + i, change_pct: code === 'SPCX' ? null : (i % 2 ? -1 : 1) * i / 10,
      quote_time: now, quote_status: code === 'SPCX' ? 'missing' : 'ready',
      data_status: code === 'SPCX' ? 'waiting' : 'ready', issues: code === 'SPCX' ? ['主数据未识别，保留原代码'] : [],
      result: code === 'SPCX' ? null : { version: 'intraday_options_v1', symbol: `${code}.US`, trading_date: '2026-11-12',
        as_of: '2026-11-12T16:00:00Z', observed_at: now, score: 95 - i, base_score: 95 - i, alignment: 1, extension_atr: 1.5,
        direction: i % 2 ? 'bearish' : 'bullish', state: i === 0 ? 'extended' : 'continuing',
        explanation: i === 0 ? '方向仍有延续，但偏离短期趋势参考线较远，标记短线延伸。' : '多个窗口方向一致，近期仍在延续。',
        structure: { kind: 'breakout_up', phase: 'confirmed', background: 'bearish', since: now, as_of: now, oversold: false,
          reference: false, available_bars: 60, missing_bars: 0, pivots: [], reasons: ['连续两根闭合K确认'],
          box: { upper: 104, lower: 102, start_at: '2026-11-12T15:20:00Z', end_at: '2026-11-12T15:50:00Z', atr: .5 } },
        windows: [5, 15, 30, 60].map(minutes => ({ minutes, data_status: 'ready', score: 95 - i, direction: i % 2 ? -1 : 1,
          return_pct: (i % 2 ? -1 : 1) * 0.65, start_at: new Date(Date.parse('2026-11-12T16:00:00Z') - minutes * 60000).toISOString(),
          end_at: '2026-11-12T16:00:00Z', stability: 82, efficiency: 90, strength: 85, disturbance: 80,
          normalized_move: 1.6, adverse_move: .2, adverse_duration: .1, movement_gate: 1, concentration: .1,
          stalled_impulse: false, reasons: [],
        })),
      },
    }));
    const bars = Array.from({ length: 91 }, (_, i) => ({ timestamp: Date.parse('2026-11-12T14:30:00Z') + i * 60000,
      open: 100 + i * .05, high: 100.2 + i * .05, low: 99.9 + i * .05, close: 100.1 + i * .05,
      volume: 1000 + i * 10, turnover: null, confirmed: i < 90, sampled: false, partial: false, sample_count: 0,
    }));
    await page.route('**/api/v1/**', route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/v1/auth/status') return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
      if (url.pathname === '/api/v1/intraday-options') return route.fulfill({ json: { trading_date: '2026-11-12',
        market_status: 'open', generated_at: now, version: 'intraday_options_v1',
        items: items.map((item, i) => changed && i === 1 ? { ...item, result: { ...item.result, score: 99 } } : item),
      } });
      if (url.pathname.includes('/market-data/intraday/')) {
        chartRequests++;
        return route.fulfill({ json: { symbol: 'SPY.US', market: 'US', trading_date: '2026-11-12', generated_at: now,
          reset: !url.searchParams.has('since'), items: bars, events: [], quote: {},
        } });
      }
      return route.fulfill({ json: { items: [] } });
    });
    await page.goto('/market/intraday-options');
    const rows = page.locator('[data-testid^="options-row-"]');
    await expect(rows).toHaveCount(30);
    await expect(rows.first()).toHaveAttribute('data-testid', 'options-row-SPY.US');
    expect(chartRequests).toBe(0);
    await rows.first().locator('td').first().click();
    const panel = page.getByTestId('options-trend-panel');
    await expect(panel).toBeVisible();
    await expect(panel.getByRole('img', { name: /1m K线/ })).toBeVisible();
    await expect(panel).toContainText('近似VWAP');
    await expect(panel.getByTestId('structure-detail')).toContainText('箱体向上突破');
    await expect(panel.getByTestId('structure-detail')).toContainText('固定箱体');
    await panel.getByRole('button', { name: '5分钟', exact: true }).click();
    await expect(panel).toContainText('5分钟 ·');
    await panel.getByRole('button', { name: '60分钟', exact: true }).click();
    await panel.getByRole('button', { name: '等权均价', exact: true }).click();
    await expect(panel).toContainText('已采集分钟收盘价等权均价');
    changed = true;
    await expect(page.getByTestId('options-row-QQQ.US').getByTestId('opportunity-score')).toHaveText('99', { timeout: 12000 });
    await expect(rows.first()).toHaveAttribute('data-testid', 'options-row-SPY.US');
    await expect(panel).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`intraday-options-${width}.png`), fullPage: true });
    await page.getByTestId('options-refresh-order').click();
    await expect(rows.first()).toHaveAttribute('data-testid', 'options-row-QQQ.US');
    await page.getByRole('button', { name: '最新价 / 涨跌幅', exact: true }).click();
    await expect(rows.last()).toHaveAttribute('data-testid', 'options-row-SPCX.US');
    await page.getByRole('button', { name: '最新价 / 涨跌幅', exact: true }).click();
    await expect(rows.last()).toHaveAttribute('data-testid', 'options-row-SPCX.US');
    await page.getByRole('group', { name: '方向筛选' }).getByRole('button', { name: '偏空', exact: true }).click();
    await expect(rows).toHaveCount(15);
    await page.getByRole('textbox', { name: '搜索标的' }).fill('INTC');
    await expect(rows).toHaveCount(1);
    expect(errors).toEqual([]);
  });
}
