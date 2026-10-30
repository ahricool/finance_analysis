import { expect, test } from '@playwright/test';
const raw = {
  market: 'CN', trade_date: '2026-09-22', candidate_trade_date: '2026-09-21',
  frozen_at: '2026-09-22T01:25:00Z', generated_at: '2026-09-22T02:00:00Z', status: 'evaluated', rule_version: 'intraday_v2', warnings: [],
  summary: { total: 1, CONFIRMED: 1, WAIT: 0, FAILED: 0 }, rules_note: 'V1 启发式规则，未经回测验证',
  items: [{ code: '600001.SH', name: '测试候选', candidate_source: 'trend', candidate_trade_date: '2026-09-21',
    candidate_reason: ['昨日正式 CANDIDATE，趋势和相对强度达到观察阈值'], source_generated_at: '2026-09-21T12:00:00Z',
    state: 'CONFIRMED', current_status: 'ACTIVE', candidate_sources: ['confluence', 'trend'], conditions: { opening_breakout: true, above_session_mean: true }, confirmation_score: 90, chase_risk: 'HIGH', generated_at: '2026-09-22T02:00:00Z',
    reasons: [{ code: 'breakout', text: '连续两根1分钟线突破开盘区间高点' }, { code: 'vwap', text: '价格高于 VWAP +4%' }],
    state_reasons: [], metrics: { quote_time: '2026-09-22T01:55:00Z', bar_time: '2026-09-22T01:55:00Z',
      gap_pct: .07, return_5m: .01, return_15m: .02, return_30m: null, volume_ratio: 1.6,
      vwap_distance_pct: .04, relative_to_market: .014, benchmark_code: '510300.SH' },
    trend: { impact: 'intact', official_trend_state: 'CANDIDATE', temporary_trend_state: 'TRENDING',
      official_lifecycle: 'EMERGING', temporary_lifecycle: 'EXPANSION', official_fragility: 18,
      calculation_basis: '固定昨日百分位，未计算盘中全市场排名' } }],
};
for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`intraday confirmation ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.addInitScript(t => localStorage.setItem('theme', t), theme);
      const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
        if (url.pathname.endsWith('/intraday-confirmation/dates')) return route.fulfill({ json: { dates: ['2026-09-22'] } });
        if (url.pathname.endsWith('/intraday-confirmation')) return route.fulfill({ json: raw });
        if (url.pathname.endsWith('/evaluations')) return route.fulfill({ json: { items: [] } });
        if (url.pathname.startsWith('/api/v1/intraday-confirmation/')) return route.fulfill({ json: raw.items[0] });
        return route.fulfill({ json: {} });
      });
      await page.goto('/research/intraday-confirmation');
      await expect(page.getByTestId('intraday-confirmation-page')).toBeVisible();
      await expect(page.getByRole('table')).toContainText('高');
      await expect(page.getByRole('table')).toContainText('确认有效');
      await expect(page.getByRole('table')).toContainText('—');
      await page.screenshot({ path: testInfo.outputPath('list.png'), fullPage: true });
      await page.getByRole('button', { name: /测试候选/ }).click();
      await page.getByRole('dialog').getByRole('tab', { name: '盘中确认', exact: true }).click();
      await expect(page.getByRole('dialog')).toContainText('形成期 → 扩张期');
      await expect(page.getByRole('dialog')).toContainText('站上全天均价');
      await expect(page.getByRole('dialog')).toContainText('评估轨迹');
      await expect(page.getByRole('dialog')).toContainText('历史：曾经确认 · 追高风险：高');
      await page.screenshot({ path: testInfo.outputPath('detail.png'), fullPage: true });
      expect(errors).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
  }
}

test('pending directions and header sorting work across the complete snapshot before pagination', async ({ page }, testInfo) => {
  const fixture = { ...raw, items: Array.from({ length: 18 }, (_, index) => ({
    ...raw.items[0], code: `ROW${index}.US`, name: `候选${index}`, state: 'WAIT',
    current_status: index === 0 ? 'PENDING_CONFIRMATION' : index === 1 ? 'PENDING_FAILURE' : 'WAIT',
    confirmation_score: index, return_3d: index / 100, return_5d: index / 200, return_10d: (18 - index) / 100,
    metrics: { ...raw.items[0]!.metrics, relative_to_market: index / 100 },
  })) };
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
    if (url.pathname.endsWith('/intraday-confirmation')) return route.fulfill({ json: fixture });
    if (url.pathname.endsWith('/dates')) return route.fulfill({ json: { dates: [] } });
    return route.fulfill({ json: {} });
  });
  await page.goto('/research/intraday-confirmation?market=US');
  const rows = page.locator('tbody tr');
  await expect(rows.first()).toContainText('ROW0.US');
  await expect(page.getByRole('table')).toContainText('走强待确认');
  await expect(page.getByRole('table')).toContainText('失效待确认');
  const score = page.getByRole('columnheader', { name: '确认分', exact: true });
  await score.getByRole('button').click();
  await score.getByRole('button').click();
  await expect(score).toHaveAttribute('aria-sort', 'descending');
  await expect(rows.first()).toContainText('ROW17.US');
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(rows).toHaveCount(3);
  await page.getByRole('columnheader', { name: '相对大盘', exact: true }).getByRole('button').click();
  await expect(rows).toHaveCount(15);
  await expect(rows.first()).toContainText('ROW0.US');
  await page.getByRole('columnheader', { name: '10日收益', exact: true }).getByRole('button').click();
  await expect(rows.first()).toContainText('ROW17.US');
  await page.getByRole('combobox', { name: '当前观察', exact: true }).click();
  await page.getByRole('option', { name: '失效待确认', exact: true }).click();
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText('ROW1.US');
  await expect(rows.first()).toContainText('失效待确认');
  await page.screenshot({ path: testInfo.outputPath('pending-failure.png'), fullPage: true });
});
