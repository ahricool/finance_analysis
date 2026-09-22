import { expect, test } from '@playwright/test';
const dates = Array.from({ length: 20 }, (_, i) => new Date(Date.UTC(2026, 7, 20 + i)).toISOString().slice(0, 10));
const day = dates.at(-1)!;
const names = ['半导体', '通信设备', '电力设备', '创新药', '有色金属', '软件服务', '汽车零部件', '银行', '食品饮料', '机械设备', '航空航天', '基础化工', '医药商业', '建筑材料', '消费电子', '计算机设备', '光伏设备', '风电设备', '证券', '保险'];
const states = ['STRONG', 'EMERGING', 'COOLING', 'NEUTRAL', 'WEAK'];
const rows = names.map((name, i) => ({
  trade_date: day, industry_code: `${881101 + i}.TI`, industry_name: name, state: states[i % 5], close: 100,
  strength_rank: i + 1, strength_score: 98 - i * 4, ret_1d: .01 - i / 1000, ret_5d: .08, ret_10d: .12, ret_20d: .2,
  rs_5d: .05, rs_10d: .08, rs_20d: .1, rank_change_1d: 6 - i, rank_change_3d: 10 - i, rank_change_5d: null,
  previous_5d_return: .03, momentum_acceleration_5d: Math.sin(i + 1) / 20, acceleration_percentile: 90 - i,
  turnover_ratio_5d: 1.6 - i / 25, up_ratio: .8 - i / 35, above_ma5_ratio: .7, above_ma20_ratio: .6,
  equal_weight_return: .012, constituent_count: 80, daily_valid_count: 78, ma5_valid_count: 78, above_ma5_count: 60, ma20_valid_count: 78, above_ma20_count: 60, up_count: 50, down_count: 26, flat_count: 2,
  data_timestamp: `${day}T07:00:00Z`, members_observed_at: `${day}T11:10:00Z`, created_at: `${day}T11:12:00Z`, updated_at: `${day}T11:12:00Z`,
  quality: { catalog_count: 20, ranked_count: 20, coverage: 1, excluded: {} },
}));

async function mockIndustryApis(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()); const path = url.pathname;
    if (path === '/api/v1/auth/status') return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
    if (path.endsWith('/ranking')) return route.fulfill({ json: { trade_date: day, expected_trade_date: day, items: rows } });
    if (path.endsWith('/dates')) return route.fulfill({ json: [...dates].reverse() });
    if (path.endsWith('/history')) return route.fulfill({ json: { dates, items: dates.flatMap((d, j) => rows.map((r, i) => ({ ...r, trade_date: d, strength_rank: 1 + (i + j) % 20 }))) } });
    if (path.endsWith('/constituents')) return route.fulfill({ json: { industry_code: path.split('/').at(-2), updated_at: `${day}T11:20:00Z`, constituent_count: 30, daily_valid_count: 30, ma5_valid_count: 30, above_ma5_count: 1, ma20_valid_count: 30, above_ma20_count: 1, items: Array.from({ length: 30 }, (_, i) => ({
      code: `${600001 + i}.SH`, name: `示例成分${i + 1}`, price: 42.5, change_pct: .035,
      trend_rank: i === 0 ? null : 31 - i, above_ma5: true, above_ma20: true, amount: 600000000,
    })) } });
    const row = rows.find(r => path.endsWith(r.industry_code));
    if (row) return route.fulfill({ json: { current: row, history: dates.map(d => ({ ...row, trade_date: d })) } });
    return route.fulfill({ json: {} });
  });
}

for (const width of [1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`industry strength ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      const errors: string[] = [];
      const memberRequests: string[] = [];
      page.on('request', request => {
        if (new URL(request.url()).pathname.endsWith('/constituents')) memberRequests.push(request.url());
      });
      page.on('pageerror', error => errors.push(error.message));
      await mockIndustryApis(page);
      await page.goto('/research/industry-strength');
      await expect(page.getByRole('heading', { name: '行业强度', exact: true })).toBeVisible();
      await expect(page.getByTestId('module-tabs').getByRole('tab', { name: '行业强度' })).toHaveAttribute('data-state', 'active');
      await expect(page.getByTestId('industry-detail-dialog')).toHaveCount(0);
      await expect(page.getByTestId('industry-ranking').locator('tbody tr')).toHaveCount(20);
      await expect(page.getByTestId('industry-summary')).toContainText('动量降速最大');
      await expect(page.getByTestId('industry-matrix').locator('canvas')).toHaveCount(1);
      if (width === 1280 && theme === 'light') {
        await page.screenshot({ path: testInfo.outputPath('industry-matrix.png'), fullPage: true });
      }
      await expect(page.getByRole('heading', { name: '排名历史', exact: true })).toBeVisible();
      await expect(page.getByTestId('industry-heatmap').locator('canvas')).toHaveCount(1);
      if (width === 1280 && theme === 'light') {
        await page.screenshot({ path: testInfo.outputPath('industry-heatmap.png'), fullPage: true });
      }
      await page.getByTestId('industry-ranking').getByRole('button', { name: '通信设备', exact: true }).click();
      await expect(page.getByTestId('industry-detail-dialog')).toContainText('通信设备');
      const dialog = page.getByTestId('industry-detail-dialog');
      await expect(dialog.getByRole('tab')).toHaveCount(0);
      for (const section of ['overview', 'history', 'constituents']) {
        await expect(dialog.getByTestId(`industry-detail-${section}`)).toHaveCount(1);
      }
      const box = await dialog.boundingBox();
      expect(Math.abs(box!.x + box!.width / 2 - width / 2)).toBeLessThan(2);
      expect(Math.abs(box!.y + box!.height / 2 - 540)).toBeLessThan(2);
      expect(box!.height).toBeLessThanOrEqual(1048);
      const membersTable = dialog.getByTestId('industry-detail-constituents').locator('table');
      await expect(membersTable.locator('tbody tr')).toHaveCount(30);
      expect(await membersTable.evaluate(el => {
        const container = el.parentElement!;
        return container.scrollHeight <= container.clientHeight + 1;
      })).toBe(true);
      if (width === 1280 && theme === 'light') {
        await page.screenshot({ path: testInfo.outputPath('industry-dialog-overview.png') });
      }
      const headerY = await dialog.locator('[data-slot="dialog-header"]').boundingBox();
      await membersTable.locator('tbody tr').nth(19).scrollIntoViewIfNeeded();
      await expect(membersTable.locator('tbody tr').nth(19)).toBeVisible();
      expect(await membersTable.locator('tbody tr').evaluateAll(elements => {
        const scroller = elements[0]!.closest('[data-testid="industry-detail-dialog"]')!.lastElementChild!;
        const viewport = scroller.getBoundingClientRect();
        return elements.filter(element => {
          const rect = element.getBoundingClientRect();
          return rect.top >= viewport.top && rect.bottom <= viewport.bottom;
        }).length;
      })).toBeGreaterThanOrEqual(20);
      expect((await dialog.locator('[data-slot="dialog-header"]').boundingBox())!.y).toBe(headerY!.y);

      await expect(page.getByTestId('industry-detail-dialog')).toContainText(`实际查询快照日期 ${day}`);
      if (width === 1280 && theme === 'light') {
        await page.screenshot({ path: testInfo.outputPath('industry-dialog.png') });
      }
      await expect(page.getByTestId('industry-constituents-banner')).toContainText('不随上方历史快照日期变化');
      await expect(page.getByTestId('industry-detail-dialog')).toContainText('示例成分1');
      const section = dialog.getByTestId('industry-detail-constituents');
      await expect(section).toContainText('当前成分股（最新数据）');
      await expect(section).toContainText('不对应上方历史日期');
      await section.getByRole('button', { name: 'Trend Rank', exact: true }).click();
      await expect(membersTable.locator('tbody tr').first()).toContainText('600030.SH');
      await expect(membersTable.locator('tbody tr').last()).toContainText('600001.SH');
      await expect(membersTable.locator('tbody tr').last().locator('td').nth(1)).toHaveText('—');
      await section.getByRole('button', { name: 'Trend Rank', exact: true }).click();
      await expect(membersTable.locator('tbody tr').first()).toContainText('600002.SH');
      await expect(membersTable.locator('tbody tr').last()).toContainText('600001.SH');
      expect(memberRequests).toHaveLength(1);
      await page.getByTestId('industry-detail-close').click();
      await expect(dialog).toHaveCount(0);
      await page.getByTestId('industry-summary-strongest').click();
      await expect(dialog).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(dialog).toHaveCount(0);
      await page.getByTestId('industry-summary-strongest').click();
      await expect(dialog).toBeVisible();
      await page.locator('[data-slot="dialog-overlay"]').click({ position: { x: 2, y: 2 } });
      await expect(dialog).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`industry-${width}-${theme}.png`), fullPage: true });
      await page.getByTestId('industry-date-picker').getByRole('button').first().click();
      const selectedRequest = page.waitForRequest(request => {
        const url = new URL(request.url());
        return url.pathname.endsWith('/industry-strength/ranking') && url.searchParams.has('trade_date');
      });
      await page.locator('[data-slot="calendar-cell-trigger"]:not([data-disabled]):not([data-unavailable]):not([data-outside-view])').first().click();
      const selectedDate = new URL((await selectedRequest).url()).searchParams.get('trade_date');
      expect(dates).toContain(selectedDate);
      await page.getByRole('button', { name: '清空日期' }).click();
      await expect(page.getByTestId('industry-date-picker')).toContainText('最新');
      expect(errors).toEqual([]);
    });
  }
}

test('industry strength ranking and dialog at 390px', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem('theme', 'light'));
  await mockIndustryApis(page);
  await page.goto('/research/industry-strength');
  await expect(page.getByTestId('industry-summary').locator('[data-slot="card"]')).toHaveCount(4);
  await page.screenshot({ path: testInfo.outputPath('industry-390-ranking.png'), fullPage: true });
  await page.getByTestId('industry-summary-strongest').click();
  const dialog = page.getByTestId('industry-detail-dialog');
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box?.width ?? 0).toBeGreaterThan(350);
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  expect(box!.height).toBeLessThanOrEqual(812);
  await expect(dialog).toContainText('5 日超额（百分点）');
  await page.screenshot({ path: testInfo.outputPath('industry-390-dialog.png') });
});

test('preview switch, async refresh and same-batch constituent details', async ({ page }, testInfo) => {
  await mockIndustryApis(page);
  await page.route('**/api/v1/auth/status', route => route.fulfill({ json: {
    loggedIn: true, user: { uid: 1, username: 'Admin', role: 'admin', extra: {} },
  } }));
  let generation = 1;
  let refreshes = 0;
  await page.route('**/api/v1/industry-strength/preview', route => route.fulfill({ json: {
    status: 'completed', error: null,
    result: {
      trade_date: day, expected_trade_date: day, source: 'preview',
      generated_at: `${day}T03:05:00Z`, data_as_of: `${day}T03:00:00Z`, data_latest_at: `${day}T03:00:10Z`,
      items: rows.map(r => ({ ...r, industry_name: `${r.industry_name}预览${generation}` })),
      constituents: Object.fromEntries(rows.map(r => [r.industry_code, {
        industry_code: r.industry_code, updated_at: `${day}T03:05:00Z`, trend_rank_date: dates.at(-2),
        constituent_count: 1, daily_valid_count: 1, ma5_valid_count: 1, ma20_valid_count: 1,
        above_ma5_count: 1, above_ma20_count: 1,
        items: [{ code: '600001.SH', name: '本批预览成分', price: 123, change_pct: .05,
          amount: 500000, volume: 100, above_ma5: true, above_ma20: true, trend_rank: 8 }],
      }])),
    },
  } }));
  await page.route('**/api/v1/industry-strength/preview/run', route => {
    generation += 1; refreshes += 1;
    return route.fulfill({ status: 202, json: { task_id: 'preview-task', status: 'pending' } });
  });
  await page.route('**/api/v1/tasks/preview-task', route => route.fulfill({ json: { status: 'completed' } }));
  await page.goto('/research/industry-strength');
  await expect(page.getByTestId('industry-snapshot-kind')).toHaveText('正式收盘');
  await page.getByTestId('industry-preview-switch').click();
  await expect(page.getByTestId('industry-date-picker')).toHaveCount(0);
  await expect(page.getByTestId('industry-snapshot-kind')).toHaveText('盘中预览');
  await expect(page.getByTestId('industry-preview-status')).toContainText('盘中累计口径');
  await page.screenshot({ path: testInfo.outputPath('industry-preview.png'), fullPage: true });
  await page.getByText('半导体预览1', { exact: true }).first().click();
  await expect(page.getByTestId('industry-detail-dialog')).toBeVisible();
  await expect(page.getByTestId('industry-detail-constituents')).toContainText('本批预览成分');
  await expect(page.getByTestId('industry-detail-constituents')).toContainText(dates.at(-2)!);
  await page.getByTestId('industry-detail-close').click();
  await page.getByTestId('industry-refresh').click();
  await expect(page.getByText('半导体预览2', { exact: true }).first()).toBeVisible();
  expect(refreshes).toBe(1);
  await page.getByTestId('industry-preview-switch').click();
  await expect(page.getByTestId('industry-snapshot-kind')).toHaveText('正式收盘');
  await expect(page.getByTestId('industry-date-picker')).toBeVisible();
});
