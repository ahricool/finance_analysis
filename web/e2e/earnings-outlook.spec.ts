import { test, expect } from '@playwright/test';

for (const width of [1280, 1440, 1920]) {
  test(`earnings outlook card and detail at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const outlook = {
      status: 'current', memberships: ['us_sp500', 'us_nasdaq100'], earnings_high: true, reaction_high: true,
      eps: { judgment: 'beat', expected_value: 1.2, consensus: null }, revenue: { judgment: 'meet', expected_value: 100, consensus: null },
      guidance: 'above', conclusion: '经营有望超预期，但近期涨幅已反映部分利好。',
      earnings_confidence: 9, reaction_confidence: 8, expected_close: 98, expected_return_pct: -2,
      intraday_low: 94, intraday_high: 103, response_direction: 'down', reference_price: 100,
      reference_price_at: '2026-10-01T20:00:00Z', reference_price_session: 'regular',
      target_trading_date: '2026-10-05', generated_at: '2026-10-01T20:10:00Z', scenarios: [],
    };
    const item = { id: 'finance_event:1', source_type: 'finance_event', source_id: 1, event_time: '2026-10-02T20:05:00Z',
      category: 'event', calendar_type: 'earnings', market: 'US', title: 'A.US 财报', summary: '', symbol: 'A.US',
      related_symbols: ['A.US'], importance: 'high', actionability: 'watch', importance_score: 8, detail_type: 'event',
      detail_payload: { counter_name: 'Example Company', market_session: 'amc', reporting_period: '2026-Q3', eps_estimate: 1.1, currency: 'USD' }, outlook };
    let detailCalls = 0;
    const filters: boolean[] = [];
    await page.route('**/api/v1/**', async route => {
      const url = new URL(route.request().url());
      let json: object = {};
      if (url.pathname.endsWith('/auth/status')) json = { loggedIn: true, user: { uid: 1, username: 'Test', role: 'user', email: 'test@example.com' } };
      else if (url.pathname.endsWith('/timeline')) {
        filters.push(url.searchParams.get('high_confidence') === 'true');
        json = { items: [item], total: 1, has_more: false, next_cursor: null, limit: 20 };
      } else if (url.pathname.endsWith('/outlook')) {
        detailCalls++;
        json = { status: 'success', summary: outlook, actual: null, versions: [{ id: 1, stage: 'final', applicability: 'valid',
          generated_at: outlook.generated_at, data_cutoff: outlook.generated_at, release_cutoff: '2026-10-02T20:00:00Z',
          prediction: outlook, search_evidence: { status: 'unverified', requested: true, configured_support: true },
          research: { sources: [], facts: [], conflicts: [] } }] };
      }
      await route.fulfill({ json });
    });
    await page.goto('/timeline');
    const card = page.getByTestId('timeline-item');
    await expect(card).toContainText('财报判断高置信度');
    await expect(card).toContainText('首日走势高置信度');
    await expect(card).toContainText('Nasdaq-100');
    expect(detailCalls).toBe(0);
    await page.getByRole('checkbox', { name: '仅高置信度' }).check();
    await expect.poll(() => filters.at(-1)).toBe(true);
    await card.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('搜索执行未能确认');
    await expect(dialog).toContainText('模型证据评分，非胜率');
    expect(detailCalls).toBe(1);
    await page.screenshot({ path: `/tmp/earnings-outlook-${width}.png`, fullPage: true, animations: 'disabled' });
    await page.emulateMedia({ colorScheme: 'dark' });
    await expect(dialog).toBeVisible();
  });
}
