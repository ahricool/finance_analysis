import { expect, test } from '@playwright/test';
import { dashboardResponse } from '../tests/fixtures/dashboard';

for (const width of [1280, 1440, 1920]) {
  test(`holdings evidence and explicit engine error at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    const requests: string[] = [];
    let failEngine = true;
    await page.route('**/api/v1/**', async route => {
      const url = new URL(route.request().url());
      const path = url.pathname;
      requests.push(path);
      if (path === '/api/v1/holdings/summary') return route.fulfill({ json: {
        market: 'CN', accounts: [{ id: 1, name: 'A股账户', market: 'CN', cash: '90000', currency: 'CNY' }], cash: '90000', market_value: '12000', total_asset: '102000', gross_exposure: '0.1176',
        positions: [{ id: 11, account_id: 1, market: 'CN', symbol: '600519.SH', asset_type: 'STOCK', quantity: '100', average_cost: '100', current_price: '120', market_value: '12000', weight: '0.1176', unrealized_pnl: '2000', trade_engine_enabled: true }],
      } });
      if (path === '/api/v1/trade-engine/positions') return route.fulfill(failEngine ? { status: 503, json: { detail: '建议服务暂不可用' } } : { json: { items: [] } });
      if (path === '/api/v1/trade-engine/signals') return route.fulfill({ json: { items: [
        { id: 1, symbol: '600519.SH', position_id: '11', evaluated_at: '2026-09-18T06:00:00Z', action: 'REDUCE', strategy_key: 'market_llm', strategy_version: '1', reason: '当时集中度过高', suggested_target_quantity: '80', evidence: { current_quantity: '100', target_quantity: '80', portfolio_reason: '控制单一标的集中度' } },
      ] } });
      if (path.endsWith('/operations')) return route.fulfill({ json: { items: [{ executed_at: '2026-09-18T07:00:00Z', side: 'SELL', quantity: '20', price: '121' }] } });
      if (path.endsWith('/markers')) return route.fulfill({ json: { items: [] } });
      if (path === '/api/v1/trend-following/600519.SH') return route.fulfill({ json: { latest: { code: '600519.SH', trade_date: '2026-09-21', state: 'TRENDING', rank: 5, alpha_score: 81, reasons: ['趋势保持向上'] } } });
      if (path === '/api/v1/quant/signals/600519.SH') return route.fulfill({ json: { trade_date: '2026-09-18', signal: 'WATCH', final_score: 72, model_version: 'v2', reasons: ['量化信号独立观察'] } });
      if (path.includes('/etf-rotation/600519')) return route.fulfill({ status: 404, json: { detail: 'not covered' } });
      if (path.endsWith('/600519.SH/context')) return route.fulfill({ json: [{ industry_code: '881101.TI', industry_name: '食品饮料', trade_date: '2026-09-21', state: 'STRONG', strength_score: 80, strength_rank: 2, members_observed_at: '2026-09-21T10:00:00Z' }] });
      if (path.endsWith('/classification')) return route.fulfill({ json: { code: '600519.SH', memberships: { indices: [], industries: [] } } });
      if (path.includes('/daily-bars/')) return route.fulfill({ json: { symbol: '600519.SH', bars: [], warnings: [] } });
      return route.fulfill({ json: dashboardResponse(url) });
    });
    await page.goto('/market/holdings');
    await expect(page.getByTestId('engine-error')).toContainText('Trade Engine 建议读取失败');
    await expect(page.getByTestId('cash')).toContainText('90,000');
    failEngine = false;
    await page.getByTestId('retry-engine').click();
    await expect(page.getByTestId('engine-error')).toHaveCount(0);
    expect(requests.filter(path => path === '/api/v1/holdings/summary')).toHaveLength(1);
    await page.getByRole('button', { name: '600519.SH', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByTestId('research-evidence')).toContainText('趋势保持向上');
    await expect(dialog.getByTestId('research-evidence')).toContainText('各模块数据日期不一致');
    await expect(dialog.getByTestId('evidence-industry')).toContainText('食品饮料');
    await dialog.locator('summary').click();
    await expect(dialog.getByTestId('signal-evidence')).toContainText('当时集中度过高');
    await expect(dialog.getByTestId('signal-evidence')).not.toContainText('趋势保持向上');
    await expect(dialog.getByTestId('evidence-trend').getByRole('link')).toHaveAttribute('href', /symbol=600519.SH.*tradeDate=2026-09-21/);
    const box = await dialog.boundingBox();
    expect(box!.width).toBeLessThan(width);
    expect(box!.width).toBeGreaterThan(800);
    expect(Math.abs(box!.x + box!.width / 2 - width / 2)).toBeLessThan(2);
    await page.screenshot({ path: testInfo.outputPath(`holdings-evidence-${width}.png`), fullPage: true });
    expect(errors).toEqual([]);
  });
}
