import { expect, test } from '@playwright/test';
const signal = {
  market: 'CN', signal_date: '2026-09-22', status: 'completed', selected_symbol: null, decision: 'NO_TRADE', confidence: 'medium',
  created_at: '2026-09-22T12:00:00Z', completed_at: '2026-09-22T12:01:00Z', model: 'test-model', prompt_version: 'signal-center-v1',
  candidate_snapshot: { captured_at: '2026-09-22T12:00:00Z', candidates: [{ symbol: '600001.SH' }], source_availability: {
    trend: { status: 'available', data_as_of: '2026-09-22', generated_at: '2026-09-22T11:00:00Z' },
    industry: { status: 'missing', data_as_of: null, generated_at: null },
  } },
  analysis: { thesis: '趋势排名靠前，但短期涨幅偏大且行业证据不足，今日不交易。', positive_signals: ['趋势保持强势'], risks: ['短线追高风险'], invalidations: ['等待回调及行业数据确认'] },
};
for (const width of [1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`signal center ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.addInitScript(t => localStorage.setItem('theme', t), theme);
      const buy = { ...signal, analysis: { ...signal.analysis, thesis: '趋势转强与相对强度共振，关注回撤风险。' }, decision: 'BUY', selected_symbol: '600001.SH', evaluation: {
        method: 'next_session_open_v1', status: 'partial', reason: null, entry_date: '2026-09-23', entry_price: 100,
        as_of: '2026-09-23', observed_sessions: 1, missing_dates: [], mfe: .12, mae: -.02, max_drawdown_close: 0,
        evaluated_at: '2026-09-23T08:00:00Z', horizons: [1, 3, 5, 10].map(days => ({
          days, target_date: ({ 1: '2026-09-23', 3: '2026-09-28', 5: '2026-09-30', 10: '2026-10-14' } as Record<number, string>)[days], status: days === 1 ? 'available' : 'pending', value: days === 1 ? .1 : null,
        })),
      } };
      const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
      await page.route('**/api/v1/**', route => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
        if (path.endsWith('/signal-center/daily')) return route.fulfill({ json: { items: [signal], requested_dates: { CN: '2026-09-22', US: '2026-09-21' } } });
        if (path.endsWith('/signal-center/history')) return route.fulfill({ json: [buy] });
        if (path.endsWith('/signal-center/CN/2026-09-22')) return route.fulfill({ json: buy });
        return route.fulfill({ json: {} });
      });
      await page.goto('/research/signal-center');
      await expect(page.getByTestId('module-tabs').getByRole('tab', { name: 'Signal Center' })).toHaveAttribute('data-state', 'active');
      await expect(page.getByRole('heading', { name: '美股 · 2026-09-21' })).toBeVisible();
      await expect(page.getByTestId('signal-card')).toContainText('当日不交易');
      await expect(page.getByTestId('signal-card')).toContainText('2026-09-22');
      await expect(page.getByText('+10.00%', { exact: true })).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath('signals.png'), fullPage: true });
      await page.getByRole('button', { name: '查看 2026-09-22 CN 信号' }).click();
      await expect(page.getByRole('dialog')).toContainText(buy.analysis.thesis);
      await expect(page.getByRole('dialog')).toContainText('2026-09-23 开盘 100.00');
      await expect(page.getByRole('dialog')).toContainText('收盘最大回撤');
      await page.screenshot({ path: testInfo.outputPath('history.png'), fullPage: true });
      expect(errors).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
  }
}
