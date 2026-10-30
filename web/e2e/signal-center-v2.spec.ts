import { expect, test } from '@playwright/test';

const day = '2026-10-29';
const picks = ['600000.SH', '510300.SH', '600001.SH'].map((symbol, index) => ({
  symbol, name: ['浦发银行', '沪深300ETF', '研究示例'][index], instrument_type: index === 1 ? 'ETF' : 'STOCK',
  confidence: 'medium', thesis: '趋势改善，位置仍需结合风险观察，证据来自当日正式快照。',
  positive_signals: ['20日趋势排名提升，中期结构保持完整。'], risks: ['短期涨幅较大，存在回撤风险。'],
  invalidations: ['收盘跌破当前趋势结构，或行业强度持续转弱。'],
  evidence: [
    { field: `${symbol}.trends.20.rank`, value: index + 1, data_as_of: day, interpretation: '趋势排名靠前，需结合价格位置判断。', supports: ['positive_signals.0', 'invalidations.0'] },
    { field: `${symbol}.trends.20.fragility_score`, value: 35, data_as_of: day, interpretation: '趋势脆弱性提示回撤风险。', supports: ['risks.0'] },
  ],
  external_sources: [{ url: 'https://example.com/announcement', title: '发行人公告', published_date: day, excerpt: '模型引用的公告信息。' }],
  evaluation: { method: 'next_session_open_v1', status: 'pending', reason: null, entry_date: null, entry_price: null,
    as_of: null, observed_sessions: 0, missing_dates: [], horizons: [], mfe: null, mae: null, max_drawdown_close: null, evaluated_at: `${day}T14:00:00Z` },
}));
const cn = { market: 'CN', signal_date: day, status: 'completed', decision: 'BUY', selected_symbol: picks[0]!.symbol,
  confidence: 'medium', recommendations: picks, created_at: `${day}T13:00:00Z`, completed_at: `${day}T13:10:00Z`,
  analysis: { thesis: '结合趋势、行业、ETF与正式共振，精选以下研究信号。', no_trade_reason: null, evidence: [] },
  candidate_snapshot: { captured_at: `${day}T13:00:00Z`, candidates: picks.map(p => ({ symbol: p.symbol })),
    source_availability: Object.fromEntries(['trend20', 'trend40', 'trend60', 'etf', 'industry', 'confluence', 'regime'].map(key => [key, { status: 'available', data_as_of: day, generated_at: `${day}T12:30:00Z` }])) },
  model: 'research-model', prompt_version: 'signal-center-v2-evidence', search_evidence: { status: 'confirmed' }, error: null };
const us = { ...cn, market: 'US', decision: 'NO_TRADE', selected_symbol: null, recommendations: [],
  analysis: { thesis: '当前候选的方向与市场环境存在冲突，缺少明确优势。', no_trade_reason: 'SIGNAL_CONFLICT', evidence: [{ field: 'market_regime.0.market_regime', value: 'DEFENSIVE', data_as_of: day, interpretation: '市场环境偏防御，与候选方向存在冲突。', supports: ['thesis'] }] } };
for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`signal research ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.addInitScript(value => localStorage.setItem('theme', value), theme);
      const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
        if (url.pathname.endsWith('/signal-center/daily')) return route.fulfill({ json: { items: [cn, us], requested_dates: { CN: day, US: day } } });
        if (url.pathname.endsWith('/signal-center/history')) return route.fulfill({ json: [cn, us] });
        if (url.pathname.includes(`/signal-center/CN/`)) return route.fulfill({ json: cn });
        return route.fulfill({ json: {} });
      });
      await page.goto('/research/signal-center');
      await expect(page.getByTestId('signal-pick')).toHaveCount(3);
      await expect(page.getByTestId('global-market-switch')).toHaveAttribute('aria-checked', 'false');
      await page.getByTestId('signal-pick').first().getByText('核验证据').click();
      await expect(page.getByText('600000.SH.trends.20.rank', { exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`signal-center-${width}-${theme}.png`), fullPage: true });
      await page.getByRole('button', { name: `查看 ${day} CN 信号`, exact: true }).click();
      await expect(page.getByRole('dialog').getByTestId('signal-pick')).toHaveCount(3);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(errors).toEqual([]);
    });
  }
}
