import { expect, test } from '@playwright/test';
const raw = {
  market: 'CN', trade_date: '2026-09-22', candidate_trade_date: '2026-09-21',
  frozen_at: '2026-09-22T01:25:00Z', generated_at: '2026-09-22T02:00:00Z', status: 'evaluated', warnings: [],
  summary: { total: 1, CONFIRMED: 1, WAIT: 0, FAILED: 0 }, rules_note: 'V1 启发式规则，未经回测验证',
  items: [{ code: '600001.SH', name: '测试候选', candidate_source: 'trend', candidate_trade_date: '2026-09-21',
    candidate_reason: ['昨日正式 CANDIDATE，趋势和相对强度达到观察阈值'], source_generated_at: '2026-09-21T12:00:00Z',
    state: 'CONFIRMED', confirmation_score: 90, chase_risk: 'HIGH', generated_at: '2026-09-22T02:00:00Z',
    reasons: [{ code: 'breakout', text: '连续两根5分钟线突破 Opening Range High' }, { code: 'vwap', text: '价格高于 VWAP +4%' }],
    state_reasons: [], metrics: { quote_time: '2026-09-22T01:55:00Z', bar_time: '2026-09-22T01:55:00Z',
      gap_pct: .07, return_5m: .01, return_15m: .02, return_30m: null, volume_ratio: 1.6,
      vwap_distance_pct: .04, relative_to_market: .014, benchmark_code: '510300.SH' },
    trend: { impact: 'intact', official_trend_state: 'CANDIDATE', temporary_trend_state: 'TRENDING',
      official_lifecycle: 'EMERGING', temporary_lifecycle: 'EXPANSION', official_fragility: 18,
      calculation_basis: '固定昨日百分位，未计算盘中全市场排名' } }],
};
for (const width of [1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`intraday confirmation ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.addInitScript(t => localStorage.setItem('theme', t), theme);
      const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
        if (url.pathname.endsWith('/intraday-confirmation')) return route.fulfill({ json: raw });
        return route.fulfill({ json: {} });
      });
      await page.goto('/research/intraday-confirmation');
      await expect(page.getByTestId('module-tabs').getByRole('tab', { name: '盘中确认' })).toHaveAttribute('data-state', 'active');
      await expect(page.getByRole('table')).toContainText('HIGH');
      await expect(page.getByRole('table')).toContainText('unavailable');
      await page.screenshot({ path: testInfo.outputPath('list.png'), fullPage: true });
      await page.getByRole('button', { name: /测试候选/ }).click();
      await expect(page.getByRole('dialog')).toContainText('EMERGING → EXPANSION');
      await expect(page.getByRole('dialog')).toContainText('Decision · CONFIRMED · Chase Risk HIGH');
      await page.screenshot({ path: testInfo.outputPath('detail.png'), fullPage: true });
      expect(errors).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
  }
}
