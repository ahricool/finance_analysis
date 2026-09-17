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
    if (path.endsWith('/constituents')) return route.fulfill({ json: { industry_code: path.split('/').at(-2), trade_date: day, members_observed_at: `${day}T11:20:00Z`, constituent_count: 2, daily_valid_count: 2, ma5_valid_count: 2, above_ma5_count: 1, ma20_valid_count: 2, above_ma20_count: 1, items: [
      { code: '600001.SH', name: '示例成分甲', price: 42.5, change_pct: .035, above_ma5: true, above_ma20: true, amount: 600000000 },
      { code: '600002.SH', name: '示例成分乙', price: 21.5, change_pct: -.021, above_ma5: false, above_ma20: true, amount: 350000000 },
    ] } });
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
      page.on('pageerror', error => errors.push(error.message));
      await mockIndustryApis(page);
      await page.goto('/research/industry-strength');
      await expect(page.getByRole('heading', { name: '行业强度', exact: true })).toBeVisible();
      await expect(page.getByTestId('module-tabs').getByRole('tab', { name: '行业强度' })).toHaveAttribute('data-state', 'active');
      await expect(page.getByTestId('industry-detail')).toHaveCount(0);
      await expect(page.getByTestId('industry-ranking').locator('tbody tr')).toHaveCount(20);
      await expect(page.getByTestId('industry-summary')).toContainText('动量降速最大');
      await page.getByTestId('industry-view-matrix').click();
      await expect(page.getByTestId('industry-matrix').locator('canvas')).toHaveCount(1);
      await page.getByTestId('industry-view-history').click();
      await expect(page.getByRole('heading', { name: '所选日 Top20 · 历史强度排名' })).toBeVisible();
      await expect(page.getByTestId('industry-heatmap').locator('canvas')).toHaveCount(1);
      await page.getByTestId('industry-view-ranking').click();
      await page.getByTestId('industry-ranking').getByRole('button', { name: '通信设备', exact: true }).click();
      await expect(page.getByTestId('industry-detail')).toContainText('通信设备');
      await expect(page.getByTestId('industry-detail')).toContainText(`实际查询快照日期 ${day}`);
      await page.getByRole('tab', { name: '当前成分股' }).click();
      await expect(page.getByTestId('industry-constituents-banner')).toContainText('不随上方历史快照日期切换');
      await expect(page.getByTestId('industry-detail')).toContainText('示例成分甲');
      await page.getByTestId('industry-drawer-close').click();
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

test('industry strength drawer is near full width at 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem('theme', 'light'));
  await mockIndustryApis(page);
  await page.goto('/research/industry-strength');
  await page.getByTestId('industry-summary-strongest').click();
  const drawer = page.getByTestId('industry-detail');
  await expect(drawer).toBeVisible();
  const box = await drawer.boundingBox();
  expect(box?.width ?? 0).toBeGreaterThan(300);
  await expect(page.getByTestId('industry-summary').locator('[data-slot="card"]')).toHaveCount(4);
});
