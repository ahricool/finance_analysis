import { expect, test, type WebSocketRoute } from '@playwright/test';

const start = Date.UTC(2026, 8, 1);
const candle = (index: number) => [start + index * 60_000, '60000', '61000', '59000',
  String(60000 + index * 3), '1.2', start + (index + 1) * 60_000 - 1, '74000', 5, '0.5', '30000'];
const snapshot = {
  symbol: 'BTCUSDT', evaluated_at: '2026-09-01T03:15:00Z', regime: 'BULL', setup: 'BREAKOUT', action: 'BUY',
  price: '60600', ema20_1h: '60500', ema50_1h: '60000', ema20_15m: '60550', breakout_level_15m: '60580',
  volume_ratio_15m: '1.5', atr14_15m: '150', initial_stop: '60300', trailing_stop: '60300',
  position_before: '0', position_after: '1', position_delta: '1', average_entry_price: '60600',
  position_state: 'LONG', reason: '1h 多头，15m 放量突破',
};
for (const width of [1280, 1440, 1920]) {
  test(`BTC candles render and update through Binance WS at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let body: object = {};
      if (path.endsWith('/auth/status')) body = { loggedIn: true, user: { uid: 1, role: 'user', username: 'Tester', extra: {} } };
      else if (path.endsWith('/crypto/btc/overview')) body = { symbol: 'BTCUSDT', strategy: snapshot, state: { position_state: 'LONG' } };
      else if (path.endsWith('/crypto/btc/performance')) body = {
        performance_start_at: snapshot.evaluated_at, performance_end_at: snapshot.evaluated_at,
        current_position: { position_pct: '1', average_entry_price: '60600' }, execution_count: 1,
        completed_cycles: 0, win_count: 0, loss_count: 0, win_rate: null, average_return: null,
        cumulative_return: '0', max_drawdown: '0', best_trade: null, worst_trade: null,
        recent_executions: [snapshot], recent_trades: [],
        equity_curve: [{ evaluated_at: snapshot.evaluated_at, equity: '1', drawdown: '0' }],
      };
      else if (path.endsWith('/crypto/btc/signals')) body = { items: [snapshot] };
      await route.fulfill({ json: body });
    });
    const marketRequests: string[] = [];
    await page.route('https://data-api.binance.vision/**', async route => {
      marketRequests.push(route.request().url());
      await route.fulfill({ json: Array.from({ length: 200 }, (_, i) => candle(i)) });
    });
    let websocket: WebSocketRoute | undefined;
    const subscriptions: { method: string; params: string[] }[] = [];
    await page.routeWebSocket('wss://data-stream.binance.vision/ws', ws => {
      websocket = ws;
      ws.onMessage(message => subscriptions.push(JSON.parse(String(message))));
    });
    await page.goto('/crypto/btc');
    await expect(page.getByTestId('crypto-btc-page')).toBeVisible();
    await expect(page.getByText('EMA20 · 1h', { exact: true })).toBeVisible();
    await expect(page.getByTestId('btc-performance')).toBeVisible();
    const chart = page.getByTestId('btc-kline-chart');
    await chart.scrollIntoViewIfNeeded();
    expect(errors).toEqual([]);
    await expect(chart.locator('canvas').first()).toBeVisible();
    expect((await chart.locator('canvas').first().boundingBox())!.height).toBeGreaterThan(250);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    websocket!.send(JSON.stringify({ e: 'aggTrade', s: 'BTCUSDT', p: '60777' }));
    await expect(page.getByText('60,777', { exact: false }).first()).toBeVisible();
    for (const label of ['5m', '15m', '1h', '4h', '1D', '1W', '1M']) {
      await page.getByTestId('btc-interval-selector').getByRole('button', { name: label, exact: true }).click();
      const interval = label === '1D' ? '1d' : label === '1W' ? '1w' : label;
      await expect.poll(() => subscriptions.at(-1)?.params).toEqual([`btcusdt@kline_${interval}`]);
      expect(marketRequests.at(-1)).toContain(`interval=${interval}`);
      await expect(chart.locator('canvas').first()).toBeVisible();
    }
    expect(subscriptions.some(item => item.method === 'UNSUBSCRIBE' && item.params[0] === 'btcusdt@kline_1m')).toBe(true);
    await page.getByTestId('btc-interval-selector').getByRole('button', { name: '15m', exact: true }).click();
    await expect.poll(() => subscriptions.at(-1)?.params).toEqual(['btcusdt@kline_15m']);
    await chart.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath('btc-chart.png') });
    await page.getByTestId('btc-performance').scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath('btc-performance.png') });
    websocket!.close({ code: 1011, reason: 'Test disconnect' });
    await expect(page.getByText('重连中', { exact: true })).toBeVisible();
    expect(errors).toEqual([]);
  });
}
