import { expect, test } from '@playwright/test';

const codes = 'SPY QQQ NVDA IWM TSLA MU AAPL AMD SPCX INTC AMZN IBIT CRWV TLT GOOGL META MSFT SOXL IREN GLD AVGO TQQQ MSTR SMH HYG SOFI SLV DRAM WULF SMCI'.split(' ');
const now = '2026-11-12T16:00:05Z';
const continuation = {
  kind: 'trend_continuation', direction: 'bullish', status: 'confirmed', quality_score: 95,
  structure_id: 'continuation:SPY', process_id: 'trend:SPY', trigger: 99.8, invalidation: 99.5, atr: .4,
  structure_start: '2026-11-12T15:56:00Z', structure_end: '2026-11-12T15:59:00Z',
  structure_high: 99.8, structure_low: 99.54, formation_start: '2026-11-12T15:56:00Z',
  started_at: '2026-11-12T15:59:00Z', confirmed_at: '2026-11-12T16:00:00Z', expires_at: '2026-11-12T16:09:00Z',
  confirmation_method: 'strong_break', atr_source: 'observed_adjacent_true_ranges', atr_samples: 20,
  components: { structure: 90, distance: 90, recovery: 90, risk: 90 }, reasons: [],
  entry_low: 99.86, entry_high: 100.12, target: null, target_source: '未知',
  opportunity_valid: true, executable: false, execution_reason: '已模拟持有，禁止重复进场或反手',
};
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
      opportunity_eligible: code !== 'SPCX',
      data_status: code === 'SPCX' ? 'waiting' : 'ready', issues: code === 'SPCX' ? ['主数据未识别，保留原代码'] : [],
      result: code === 'SPCX' ? null : { version: 'intraday_options_v1', symbol: `${code}.US`, trading_date: '2026-11-12',
        as_of: '2026-11-12T16:00:00Z', observed_at: now, score: 95 - i, base_score: 95 - i, alignment: 1, extension_atr: 1.5,
        opportunities: { version: 'intraday_entry_v1', reference: false, missing_bars: 0, as_of: now, reasons: [],
          primary: i === 0 ? continuation : { kind: 'box_breakout', direction: 'bullish', status: 'confirmed', quality_score: 95 - i },
          branches: i === 0 ? [continuation] : [] },
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
        items: items.map((item, i) => changed && i === 1 ? { ...item, result: { ...item.result, score: 99, opportunities: { ...item.result?.opportunities, primary: { ...item.result?.opportunities.primary, quality_score: 99 } } } } : item),
      } });
      if (url.pathname.includes('/market-data/intraday/')) {
        chartRequests++;
        return route.fulfill({ json: { symbol: 'SPY.US', market: 'US', trading_date: '2026-11-12', generated_at: now,
          reset: !url.searchParams.has('since'), items: bars, events: [], quote: {},
        } });
      }
      return route.fulfill({ json: { items: [] } });
    });
    await page.routeWebSocket('**/api/v1/market-data/ws?**', ws => {
      const send = () => ws.send(JSON.stringify({ type: 'quotes', quotes: [], generated_at: now,
        intraday_options: { trading_date: '2026-11-12', market_status: 'open', generated_at: now,
          version: 'intraday_options_v8',
          items: items.map((item, i) => changed && i === 1 ? { ...item, result: { ...item.result, score: 99,
            opportunities: { ...item.result?.opportunities, primary: { ...item.result?.opportunities.primary, quality_score: 99 } } } } : item),
          simulation: {
            states: ['SPY.US', 'NVDA.US'].map((symbol, i) => ({ symbol, plans: i ? [] : [continuation],
              position: { id: symbol, symbol, side: i ? -1 : 1, kind: 'trend_continuation', confirmation_method: 'strong_break',
              entry_price: 100, entry_at: now, last_price: 101, last_price_at: now, return_pct: i ? -1 : 1,
              invalidation: i ? 102 : 99, protection: i ? 102 : 99, target: i ? 97 : 103 } })),
            trades: [], statistics: [], events: [
              { id: 1, kind: 'entry', symbol: 'SPY.US', at: now, reason: '模拟做多进场', side: 1 },
              { id: 2, kind: 'entry', symbol: 'NVDA.US', at: now, reason: '模拟做空进场', side: -1 },
            ],
          },
        } }));
      send();
      const timer = setInterval(send, 1000);
      ws.onClose(() => clearInterval(timer));
    });
    await page.goto('/market/intraday-options');
    await expect(page.getByTestId('simulation-position')).toHaveCount(2);
    await expect(page.getByTestId('simulation-event')).toHaveCount(2);
    await expect(page.getByTestId('simulation-event').first()).toContainText(/NVDA.US\s*做空/);
    await expect(page.getByTestId('simulation-event').first()).toBeVisible();
    const rows = page.locator('[data-testid^="options-row-"]');
    await expect(rows).toHaveCount(30);
    await expect(rows.first()).toHaveAttribute('data-testid', 'options-row-SPY.US');
    expect(chartRequests).toBe(0);
    await rows.first().locator('td').first().click();
    const panel = page.getByTestId('options-trend-panel');
    await expect(panel).toBeVisible();
    await expect(panel.getByRole('img', { name: /1m K线/ })).toBeVisible();
    await expect(panel).toContainText('近似VWAP');
    await expect(panel.getByTestId('simulation-chart-markers')).toContainText('1 条模拟进退场');
    await panel.getByRole('combobox', { name: '定位模拟成交' }).click();
    await page.getByRole('option').filter({ hasText: '模拟记录' }).first().click();
    await expect(panel.getByTestId('simulation-trade-detail')).toContainText('B · 模拟做多进场');
    await expect(panel.getByTestId('simulation-trade-detail')).toContainText('100.00');
    await expect(panel.getByTestId('simulation-trade-detail')).toContainText('趋势延续 · 强突破单根确认');
    await expect(panel.getByTestId('opportunity-detail')).toContainText('日内机会');
    await expect(panel.getByTestId('opportunity-detail')).toContainText('强突破单根确认');
    await expect(panel.getByTestId('opportunity-detail')).toContainText('已模拟持有，禁止重复进场或反手');
    await expect(panel.getByTestId('opportunity-detail')).toContainText('20 个真实相邻波动样本');
    await expect(panel.getByTestId('structure-detail')).toContainText('箱体向上突破');
    await expect(panel.getByTestId('structure-detail')).toContainText('固定箱体');
    await panel.getByRole('button', { name: '5分钟', exact: true }).click();
    await expect(panel).toContainText('5分钟 ·');
    await panel.getByRole('button', { name: '60分钟', exact: true }).click();
    await panel.getByRole('button', { name: '等权均价', exact: true }).click();
    await expect(panel).toContainText('已采集分钟收盘价等权均价');
    changed = true;
    await expect(page.getByTestId('options-row-QQQ.US').getByTestId('opportunity-score')).toContainText('99', { timeout: 12000 });
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
