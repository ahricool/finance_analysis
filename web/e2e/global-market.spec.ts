import { expect, test, type Page } from '@playwright/test';

async function mockMarkets(page: Page) {
  const reads: URL[] = [];
  const sockets: URL[] = [];
  await page.routeWebSocket('**/api/v1/market-data/ws*', socket => {
    sockets.push(new URL(socket.url()));
    socket.send(JSON.stringify({ type: 'quotes', generated_at: new Date().toISOString(), quotes: [] }));
  });
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url()); reads.push(url);
    const path = url.pathname;
    const market = url.searchParams.get('market') || 'CN';
    let json: unknown;
    if (path.endsWith('/auth/status')) json = { loggedIn: true, user: { uid: 1, username: 'Tester', email: 'tester@example.test', role: 'admin' } };
    else if (path.endsWith('/timeline')) json = { items: [], total: 0, has_more: false };
    else if (path.endsWith('/watch-list/tags')) json = [];
    else if (path.endsWith('/watch-list')) json = { items: [], total: 0 };
    else if (path.endsWith('/holdings/summary')) json = { market, accounts: [], positions: [], cash: '0', market_value: '0', total_asset: '0', gross_exposure: null };
    else if (path.endsWith('/market-heatmap')) json = { status: 'empty', snapshot: null };
    else if (path.endsWith('/signal-center/daily')) json = { items: [], requested_dates: { CN: '2026-10-29', US: '2026-10-29' } };
    else if (path.endsWith('/signal-center/history')) json = [];
    else return route.fulfill({ status: 404, json: { detail: 'No saved snapshot' } });
    return route.fulfill({ json });
  });
  return { reads, sockets };
}

for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  test(`shared market follows navigation, refresh and disabled pages at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { reads, sockets } = await mockMarkets(page);
    const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto('/timeline');
    const control = page.getByTestId('global-market-switch');
    await expect(control).toHaveAttribute('aria-checked', 'false');
    await expect(page.getByText('全部市场', { exact: true })).toHaveCount(0);
    await expect.poll(() => reads.findLast(url => url.pathname.endsWith('/timeline'))?.searchParams.get('market')).toBe('CN');
    await control.press('Space');
    await expect(control).toHaveAttribute('aria-checked', 'true');
    await expect.poll(() => reads.findLast(url => url.pathname.endsWith('/timeline'))?.searchParams.get('market')).toBe('US');
    const box = await control.boundingBox();
    const avatar = await page.getByRole('button', { name: '打开用户菜单' }).boundingBox();
    expect(box!.x + box!.width).toBeLessThan(avatar!.x);
    if (width >= 1024) {
      const navEnd = await page.getByTestId('desktop-main-nav').getByRole('button', { name: '任务中心', exact: true }).boundingBox();
      const marketControl = await page.getByTestId('global-market-control').boundingBox();
      expect(navEnd!.x + navEnd!.width + 4).toBeLessThanOrEqual(marketControl!.x);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.goto('/dashboard');
    await expect(control).toBeDisabled();
    await page.goto('/profile/info');
    await expect(control).toBeDisabled();
    await page.goto('/research/industry-strength');
    await expect(control).toBeDisabled();
    await expect(control).toHaveAttribute('aria-checked', 'false');
    await page.goto('/market/watch-list');
    await expect(control).toBeEnabled();
    await expect(control).toHaveAttribute('aria-checked', 'true');
    await expect.poll(() => reads.findLast(url => url.pathname.endsWith('/watch-list'))?.searchParams.get('market')).toBe('US');
    await expect.poll(() => sockets.at(-1)?.searchParams.get('market')).toBe('US');
    await page.reload();
    await expect(control).toHaveAttribute('aria-checked', 'true');
    await control.click();
    await expect.poll(() => reads.findLast(url => url.pathname.endsWith('/watch-list'))?.searchParams.get('market')).toBe('CN');
    await expect.poll(() => sockets.at(-1)?.searchParams.get('market')).toBe('CN');
    expect(errors).toEqual([]);
  });
}

test('every selectable page requests the shared market and signal pagination is scoped on the server', async ({ page }) => {
  const { reads } = await mockMarkets(page);
  await page.addInitScript(() => localStorage.setItem('selected_market', 'US'));
  const pages = [
    ['/market/holdings', '/api/v1/holdings/summary'],
    ['/market/heatmap', '/api/v1/market-heatmap'],
    ['/research/etf-rotation', '/api/v1/etf-rotation/preview/status'],
    ['/research/trend-following', '/api/v1/trend-following/status'],
    ['/research/confluence', '/api/v1/confluence/ranking'],
    ['/research/intraday-confirmation', '/api/v1/intraday-confirmation'],
    ['/research/quant', '/api/v1/quant/status'],
    ['/strategies', '/api/v1/stock-strategies'],
    ['/research/signal-center', '/api/v1/signal-center/daily'],
  ];
  for (const [path, endpoint] of pages) {
    reads.length = 0;
    await page.goto(path!);
    await expect(page.getByTestId('global-market-switch')).toBeEnabled();
    await expect.poll(() => reads.find(url => url.pathname === endpoint)?.searchParams.get('market')).toBe('US');
    await expect(page.locator('main [role="radiogroup"][aria-label="市场"], main [aria-label="自选股市场"], main [aria-label="投资组合市场"], main [aria-label="热力图市场"]')).toHaveCount(0);
  }
  await expect.poll(() => reads.find(url => url.pathname.endsWith('/signal-center/history'))?.searchParams.get('market')).toBe('US');
  await page.getByTestId('global-market-switch').click();
  await expect.poll(() => reads.findLast(url => url.pathname.endsWith('/signal-center/daily'))?.searchParams.get('market')).toBe('CN');
  await expect.poll(() => reads.findLast(url => url.pathname.endsWith('/signal-center/history'))?.searchParams.get('market')).toBe('CN');
});

for (const theme of ['light', 'dark'] as const) {
  test(`market switch uses theme colors and moves its thumb in ${theme} mode`, async ({ page }) => {
    await mockMarkets(page);
    await page.addInitScript(value => localStorage.setItem('theme', value), theme);
    await page.goto('/timeline?market=CN');
    const control = page.getByTestId('global-market-switch');
    const thumb = control.locator('[data-slot="switch-thumb"]');
    await expect(control).toHaveAttribute('data-slot', 'switch');
    await expect(control).toHaveAttribute('data-state', 'unchecked');
    const before = await thumb.boundingBox();
    await control.press('Space');
    await expect(control).toHaveAttribute('data-state', 'checked');
    await expect(thumb).toHaveAttribute('data-state', 'checked');
    await expect.poll(async () => (await thumb.boundingBox())!.x).toBeGreaterThan(before!.x + 10);
    const brand = await page.getByRole('button', { name: '今天', exact: true }).evaluate(el => getComputedStyle(el).backgroundColor);
    await expect(control).toHaveCSS('background-color', brand);
    expect(await thumb.evaluate(el => getComputedStyle(el).backgroundColor)).not.toBe(brand);
    await page.goto('/profile/info');
    await expect(control).toBeDisabled();
    await expect(control).toHaveCSS('opacity', '0.5');
    expect(await control.evaluate(el => getComputedStyle(el).backgroundColor)).not.toBe(brand);
  });
}
