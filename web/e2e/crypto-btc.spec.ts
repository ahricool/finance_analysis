import { expect, test, type WebSocketRoute } from '@playwright/test';

const start = Date.UTC(2026, 8, 1);
const candle = (index: number, closed = true) => ({
  symbol: 'BTCUSDT', interval: '1m', source: 'binance',
  open_time: new Date(start + index * 60_000).toISOString(), close_time: new Date(start + (index + 1) * 60_000).toISOString(),
  open: String(60000 + index * 3), high: String(60030 + index * 3), low: String(59980 + index * 3),
  close: String(60000 + index * 3 + (index % 2 ? -10 : 15)), volume: '1.234567890123', quote_volume: '74000',
  trade_count: 5, taker_buy_volume: '0.5', taker_buy_quote_volume: '30000', closed,
});
const snapshot = {
  symbol: 'BTCUSDT', evaluated_at: '2026-09-01T03:15:00Z', regime: 'BULL', setup: 'BREAKOUT', action: 'BUY',
  price: '60600', ema20_1h: '60500', ema50_1h: '60000', ema20_15m: '60550', breakout_level_15m: '60580',
  volume_ratio_15m: '1.5', atr14_15m: '150', initial_stop: '60300', trailing_stop: '60300',
  position_state: 'LONG', reason: '1h 多头，15m 放量突破',
};
const market = {
  symbol: 'BTCUSDT', enabled: true, ready: true, stream_mode: 'websocket', websocket_connected: true,
  last_update_time: '2026-09-01T03:20:00Z', last_websocket_message_time: '2026-09-01T03:20:00Z', last_error: null,
  latest_candle: candle(200, false), recent_closed: [candle(199)], strategy_latest_state: snapshot,
};

for (const width of [1280, 1440]) {
  test(`BTC candles render and update through backend WS at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let body: object = {};
      if (path.endsWith('/auth/status')) body = { loggedIn: true, user: { uid: 1, role: 'user', username: 'Tester', extra: {} } };
      else if (path.endsWith('/crypto/btc/klines')) body = { items: Array.from({ length: 200 }, (_, i) => candle(i)) };
      else if (path.endsWith('/crypto/btc/overview')) body = { symbol: 'BTCUSDT', market, strategy: snapshot, state: { position_state: 'LONG' } };
      else if (path.endsWith('/crypto/btc/signals')) body = { items: [snapshot] };
      await route.fulfill({ json: body });
    });
    let websocket: WebSocketRoute | undefined;
    await page.routeWebSocket('**/api/v1/crypto/ws', ws => {
      websocket = ws;
      ws.send(JSON.stringify({ type: 'state', market }));
    });
    await page.goto('/market/crypto/btc');
    await expect(page.getByTestId('crypto-btc-page')).toBeVisible();
    await expect(page.getByText('EMA20 · 1h', { exact: true })).toBeVisible();
    const chart = page.getByTestId('btc-kline-chart');
    await chart.scrollIntoViewIfNeeded();
    expect(errors).toEqual([]);
    await expect(chart.locator('canvas')).toBeVisible();
    expect((await chart.locator('canvas').boundingBox())!.height).toBeGreaterThan(250);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    websocket!.send(JSON.stringify({ type: 'state', market: { ...market, latest_candle: { ...candle(200, false), close: '60777', high: '60790' } } }));
    await expect(page.getByText('60,777', { exact: false }).first()).toBeVisible();
    await chart.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath('btc-chart.png') });
    websocket!.close({ code: 1011, reason: 'Test disconnect' });
    await expect(page.getByTestId('crypto-fallback')).toBeVisible();
    expect(errors).toEqual([]);
  });
}
