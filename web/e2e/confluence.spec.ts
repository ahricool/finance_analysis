import { expect, test } from '@playwright/test';
import raw from './fixtures/confluenceV22';

for (const width of [390, 768, 1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`Confluence evidence ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.addInitScript(t => localStorage.setItem('theme', t), theme);
      const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
        if (url.pathname.includes('/market-data/daily-bars/')) return route.fulfill({ json: {
          symbol: '600001.SH', market: 'CN', interval: '1d', adjustment: 'forward', source: 'database',
          items: Array.from({ length: 30 }, (_, index) => ({
            trade_date: new Date(Date.UTC(2026, 8, 1 + index)).toISOString().slice(0, 10),
            open: 10 + index * .1, high: 10.5 + index * .1, low: 9.8 + index * .1,
            close: 10.3 + index * .1, volume: 10000 + index * 100, amount: null,
          })),
        } });
        if (url.pathname.endsWith('/classification')) return route.fulfill({ json: { code: '600001.SH', market: 'CN', memberships: { indices: [], industries: [] }, etf_proxies: [] } });
        if (url.pathname.endsWith('/dates')) return route.fulfill({ json: ['2026-09-22'] });
        if (url.pathname.endsWith('/ranking')) return route.fulfill({ json: raw });
        if (url.pathname.startsWith('/api/v1/confluence/')) return route.fulfill({ json: { market: raw.market, trade_date: raw.trade_date, algorithm_version: raw.algorithm_version, rules: raw.rules, item: raw.items.find(r => r.code === decodeURIComponent(url.pathname.split('/').at(-1)!)) ?? raw.items[0] } });
        return route.fulfill({ json: {} });
      });
      await page.goto('/research/confluence');
      if (width >= 1024) await expect(page.getByTestId('module-tabs').getByRole('link', { name: '多信号共振' })).toHaveAttribute('data-state', 'active');
      await expect(page.getByRole('table')).toContainText('84.0');
      await expect(page.getByRole('table')).toContainText('4/4');
      await expect(page.getByRole('table')).toContainText('2026-09-21');
      await expect(page.getByRole('table')).toContainText('期权情报');
      await page.getByRole('button', { name: /测试股票/ }).click();
      const dialog = page.getByRole('dialog');
      await expect(dialog.getByTestId('daily-kline-card')).toBeVisible();
      await expect(dialog.getByTestId('daily-kline-card').locator('canvas').first()).toBeVisible();
      await dialog.getByRole('tab', { name: '共振', exact: true }).click();
      await expect(dialog.getByTestId('evidence-industry')).toContainText('92');
      await expect(dialog.getByTestId('macro-adaptation')).toContainText('A股成长风格');
      await expect(dialog.getByTestId('macro-adaptation')).toContainText('+24.00');
      await dialog.getByTestId('evidence-industry').getByText('评分依据', { exact: true }).click();
      await expect(dialog).toContainText('12 → 4');
      await expect(dialog.getByTestId('evidence-trend')).toContainText('60D');
      await expect(dialog.getByTestId('evidence-options')).toContainText('缺失');
      await expect(dialog).toContainText('Why Confluence');
      await dialog.getByTestId('evidence-macro').screenshot({ path: testInfo.outputPath(`macro-adaptation-${width}-${theme}.png`) });
      await page.screenshot({ path: testInfo.outputPath(`confluence-detail-${width}-${theme}.png`), fullPage: true });
      await page.keyboard.press('Escape');
      await page.screenshot({ path: testInfo.outputPath(`confluence-${width}-${theme}.png`), fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(errors).toEqual([]);
    });
  }
}

test('filters, partial US coverage and failed request clear old data', async ({ page }) => {
  let fail = false; const params: URLSearchParams[] = [];
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
    if (url.pathname.endsWith('/dates')) return route.fulfill({ json: ['2026-09-22'] });
    if (url.pathname.endsWith('/ranking')) {
      params.push(url.searchParams);
      return fail ? route.fulfill({ status: 503, json: { detail: 'Unavailable' } }) : route.fulfill({ json: url.searchParams.get('market') === 'US' ? { ...raw, market: 'US', items: [], total: 0 } : raw });
    }
    return route.fulfill({ json: {} });
  });
  await page.goto('/research/confluence');
  await expect(page.getByRole('table')).toContainText('测试股票');
  await page.getByLabel('最低有效维度', { exact: true }).fill('4');
  await page.getByLabel('最低分数', { exact: true }).fill('80');
  await page.getByRole('button', { name: '筛选', exact: true }).click();
  await expect.poll(() => params.at(-1)?.get('min_signals')).toBe('4');
  expect(params.at(-1)?.get('min_score')).toBe('80');
  await page.getByTestId('confluence-market-switcher').getByRole('radio', { name: '美股' }).click();
  await expect(page.getByRole('table')).toContainText('暂无符合条件');
  await expect(page.getByText('缺少核心证据时留空；每日上限是 10 个，不是必须产出 10 个。')).toBeVisible();
  fail = true;
  await page.getByRole('button', { name: '刷新共振', exact: true }).click();
  await expect(page.getByRole('table')).toHaveCount(0);
});

test('snapshot changes restore saved default signal count while manual filters remain explicit', async ({ page }) => {
  const requests: URLSearchParams[] = [];
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
    if (url.pathname.endsWith('/dates')) return route.fulfill({ json: ['2026-09-22', '2026-09-21'] });
    if (url.pathname.endsWith('/ranking')) {
      requests.push(url.searchParams);
      const historical = url.searchParams.get('trade_date') === '2026-09-21';
      return route.fulfill({ json: { ...raw, trade_date: historical ? '2026-09-21' : '2026-09-22',
        rules: { ...raw.rules, min_signals: historical ? 3 : 4 } } });
    }
    return route.fulfill({ json: {} });
  });
  await page.goto('/research/confluence');
  const signals = page.getByLabel('最低有效维度', { exact: true });
  await expect(signals).toHaveValue('4');
  expect(requests[0]?.has('min_signals')).toBe(false);

  await page.getByRole('button', { name: '快照日期', exact: true }).click();
  await page.locator('[data-slot="calendar-cell-trigger"][data-value="2026-09-21"]').click();
  await expect(signals).toHaveValue('3');
  expect(requests.at(-1)?.get('trade_date')).toBe('2026-09-21');
  expect(requests.at(-1)?.has('min_signals')).toBe(false);

  await signals.fill('5');
  await page.getByRole('button', { name: '筛选', exact: true }).click();
  await expect.poll(() => requests.at(-1)?.get('min_signals')).toBe('5');
  await expect(page.getByRole('button', { name: '筛选', exact: true })).toBeEnabled();
  await expect(signals).toHaveValue('5');

  await page.getByTestId('confluence-market-switcher').getByRole('radio', { name: '美股' }).click();
  await expect(signals).toHaveValue('4');
  expect(requests.at(-1)?.get('market')).toBe('US');
  expect(requests.at(-1)?.has('min_signals')).toBe(false);
});


for (const width of [390, 1440]) {
test(`research top fifty pagination and observation detail ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 });
  await page.addInitScript(t => localStorage.setItem('theme', t), width === 390 ? 'dark' : 'light');
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
    if (url.pathname.endsWith('/dates')) return route.fulfill({ json: ['2026-09-22'] });
    if (url.pathname.endsWith('/ranking')) return route.fulfill({ json: raw });
    if (url.pathname.startsWith('/api/v1/confluence/')) return route.fulfill({ json: { market: raw.market, trade_date: raw.trade_date, algorithm_version: raw.algorithm_version, rules: raw.rules,
      item: raw.items.find(r => r.code === decodeURIComponent(url.pathname.split('/').at(-1)!)) } });
    if (url.pathname.endsWith('/classification')) return route.fulfill({ json: { code: '600021.SH', market: 'CN', memberships: { indices: [], industries: [] }, etf_proxies: [] } });
    return route.fulfill({ json: {} });
  });
  await page.goto('/research/confluence');
  const pagination = page.getByTestId('confluence-pagination');
  await expect(page.locator('tbody tr')).toHaveCount(10);
  await expect(page.getByTestId('selected-count')).toContainText('10');
  await expect(pagination).toContainText('第 1 / 5 页');
  await pagination.getByRole('button', { name: '下一页' }).click();
  await pagination.getByRole('button', { name: '下一页' }).click();
  await expect(pagination).toContainText('第 3 / 5 页');
  await expect(page.getByTestId('below-threshold')).toHaveCount(10);
  await page.screenshot({ path: testInfo.outputPath('research-observations-page3.png'), fullPage: true });
  await page.locator('tbody tr').first().click();
  await expect(page.getByTestId('confluence-selection-status')).toContainText('研究观察项');
  await expect(page.getByTestId('confluence-selection-status')).toContainText('低于60分');
  await expect(page.getByTestId('confluence-selection-status')).not.toContainText('当日精选信号');
  await page.keyboard.press('Escape');
  await pagination.getByRole('button', { name: '下一页' }).click();
  await pagination.getByRole('button', { name: '下一页' }).click();
  await expect(pagination).toContainText('第 5 / 5 页');
  await expect(pagination.getByRole('button', { name: '下一页' })).toBeDisabled();
  await page.getByRole('button', { name: '刷新共振' }).click();
  await expect(pagination).toContainText('第 1 / 5 页');
});

}
