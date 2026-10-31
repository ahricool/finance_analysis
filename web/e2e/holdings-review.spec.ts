import { expect, test } from '@playwright/test';

function result(market: string, day: string) {
  const cn = market === 'CN';
  const position = { position_id: '11', account_id: '1', symbol: cn ? '600519.SH' : 'AAPL.US', name: cn ? '贵州茅台' : 'Apple', quantity: 100, average_cost: 100, current_price: 120, unrealized_pnl_pct: 20, weight_pct: 12, today_buy_quantity: 0 };
  return { today: '2026-10-30', previous_trade_date: '2026-10-29', requested_date: day,
    scheduled_at: '2026-10-30T06:10:00Z', can_run: false,
    review: { id: 1, market, trade_date: day, status: 'completed', as_of: '2026-10-30T06:10:00Z',
      portfolio: { cash: 30000, nav: 100000, currency: cn ? 'CNY' : 'USD', valuation_complete: true },
      holdings: [position],
      decision: { market_state: 'NEUTRAL', confidence: 'MEDIUM', degraded: false,
        conclusion: '指数维持震荡，结构性机会仍在。已有持仓以确认后的调整为主，避免在尾盘扩大不确定性。',
        sectors: [{ name: '科技与先进制造', strength: 'STRONG', rationale: 'ETF 动量与盘中预演共同显示相对强度，仍需观察成交延续。' }, { name: '消费与防御', strength: 'NEUTRAL', rationale: '分化尚未收敛，以已有持仓的趋势证据为主。' }],
        risks: [{ title: '盘中信号仍需确认', severity: 'MEDIUM', detail: '临时日 K 与成交量会继续变化，不将预演排名视为收盘结论。' }],
        watchpoints: ['关注主要指数尾盘能否守住当日观察区间。', '加仓前核对现金和实际可交易数量。'],
        positions: [{ position_id: '11', symbol: position.symbol, action: 'BUY', change_pct: 10, confidence: 'MEDIUM', rationale: '当前价格与成本形成一定缓冲，趋势预演保持稳定；建议在条件确认后小幅加仓。', condition: '价格守住观察区间，且登记现金与券商可用余额一致。', invalidation: '价格跌回观察区间，或出现新的重大负面公告。' }] },
      indices: (cn ? ['上证指数', '创业板指', '沪深300'] : ['标普500指数', '纳斯达克100指数', '道琼斯指数']).map((name, i) => ({ symbol: String(i), name, current_price: 4000 + i * 300, change_pct: i === 1 ? -0.2 : 0.5 })),
      research: { etf_rotation: { status: 'available', observed_at: '2026-10-30T06:00:00Z', items: [{}] }, holding_trends: { status: 'available', observed_at: '2026-10-30T06:00:00Z', items: [{}] }, industry_strength: { status: cn ? 'available' : 'unsupported', observed_at: '2026-10-30T06:00:00Z', items: [] } },
      search_evidence: { status: 'unverified', citations: [] }, data_quality: [], markdown: '# 每日持仓复盘' } };
}
for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`holdings review layout and history ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.addInitScript(value => { localStorage.setItem('theme', value); }, theme);
      const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
      const reads: string[] = [];
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url()); const market = url.searchParams.get('market') || 'CN';
        if (url.pathname.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'admin', email: 'test@example.com' } } });
        if (url.pathname.endsWith('/holdings-review/dates')) return route.fulfill({ json: { items: [{ trade_date: '2026-10-30', status: 'completed' }, { trade_date: '2026-10-29', status: 'completed' }] } });
        if (url.pathname.endsWith('/holdings-review')) { const day = url.searchParams.get('trade_date') || '2026-10-30'; reads.push(day); return route.fulfill({ json: result(market, day) }); }
        return route.fulfill({ status: 404, json: { detail: 'not covered' } });
      });
      await page.goto('/market/holdings-review');
      await expect(page.getByTestId('review-market-conclusion')).toContainText('结构性机会');
      await expect(page.getByTestId('review-holdings')).toContainText('加仓');
      await page.getByRole('button', { name: '上一份复盘', exact: true }).click();
      await expect(page.getByText('历史快照', { exact: true })).toBeVisible();
      expect(reads.at(-1)).toBe('2026-10-29');
      await page.getByRole('button', { name: '最新复盘', exact: true }).click();
      await expect(page.getByText('历史快照', { exact: true })).toHaveCount(0);
      await expect(page.getByTestId('review-position-row')).toContainText('贵州茅台');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
      expect(overflow).toBe(false);
      await page.screenshot({ path: testInfo.outputPath(`holdings-review-${width}-${theme}.png`), fullPage: true });
      await page.getByTestId('global-market-switch').press('Space');
      await expect(page.getByTestId('review-position-row')).toContainText('Apple');
      expect(errors).toEqual([]);
    });
  }
}
