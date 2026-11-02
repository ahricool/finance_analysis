import { expect, test, type Page } from '@playwright/test';
import fs from 'node:fs';

const bars = { symbol: '600519.SH', market: 'CN', interval: '1d', adjustment: 'forward', source: 'test',
  items: Array.from({ length: 21 }, (_, i) => ({ trade_date: `2026-10-${String(i + 10).padStart(2, '0')}`, open: 100 + i, high: 101 + i, low: 99 + i, close: 100 + i, volume: 1000, amount: null })) };
interface Replay { code: string; name: string; market: string; bars: typeof bars; options: Record<string, unknown> | null }
async function openOptions(page: Page, sample: Replay, requests: string[]) {
  const item = { code: sample.code, name: sample.name, candidate_source: 'trend', candidate_sources: ['trend'], candidate_trade_date: '2026-10-29',
    candidate_reason: ['昨日正式趋势'], source_generated_at: '2026-10-29T12:00:00Z', state: 'WAIT', current_status: 'WAIT', confirmation_score: null,
    available_score_weight: 0, chase_risk: 'UNKNOWN', generated_at: null, first_confirmed_at: null, failed_at: null,
    reasons: [], state_reasons: [], metrics: {}, trend: {}, current_price_recovered: false };
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url()), path = url.pathname;
    requests.push(route.request().method() + ' ' + path + url.search);
    if (path.endsWith('/auth/status')) return route.fulfill({ json: { loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} } } });
    if (path.endsWith('/classification')) return route.fulfill({ json: { code: sample.code, market: sample.market, memberships: { industries: [], indices: [] }, etf_proxies: [] } });
    if (path.includes('/daily-bars/')) return route.fulfill({ json: sample.bars });
    if (path.endsWith('/evaluations')) return route.fulfill({ json: { items: [] } });
    if (path.endsWith('/intraday-confirmation/dates')) return route.fulfill({ json: { dates: ['2026-10-30'] } });
    if (path.endsWith('/intraday-confirmation')) return route.fulfill({ json: { market: sample.market, trade_date: '2026-10-30', candidate_trade_date: '2026-10-29',
      frozen_at: null, generated_at: null, status: 'frozen', warnings: [], rule_version: 'intraday_v2', rules_note: '', summary: { total: 1, WAIT: 1, CONFIRMED: 0, FAILED: 0 }, items: [item] } });
    if (path.startsWith('/api/v1/intraday-confirmation/')) return route.fulfill({ json: item });
    if (path.startsWith('/api/v1/options-intelligence/')) return route.fulfill({ json: sample.options ?? { symbol: sample.code, latest: null, daily_history: [], events: [], analyses: [], reason: '所选日期尚无正式期权数据' } });
    return route.fulfill({ json: {} });
  });
  await page.goto(`/research/intraday-confirmation?market=${sample.market}`);
  await page.locator('tbody tr').first().click();
  await page.getByRole('dialog').getByRole('tab', { name: '期权', exact: true }).click();
  await expect(page.getByTestId('option-strategy-panel')).toBeVisible();
  await expect(page.locator('[data-score]').first()).toBeVisible();
}
const cn = { code: '600519.SH', name: '测试标的', market: 'CN', bars, options: null };
for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  for (const theme of ['light', 'dark']) {
    test(`option strategies CN ${width}px ${theme}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(t => localStorage.setItem('theme', t), theme);
      const errors: string[] = [], requests: string[] = [];
      page.on('pageerror', e => errors.push(e.message));
      await openOptions(page, cn, requests);
      const panel = page.getByTestId('option-strategy-panel');
      await expect(page.getByRole('dialog')).toContainText('暂无期权数据');
      await expect(panel.getByTestId('option-horizon-swing')).toHaveAttribute('aria-pressed', 'true');
      const scores = await panel.locator('[data-score]').evaluateAll(els => els.map(e => Number(e.getAttribute('data-score'))));
      expect(scores).toEqual([...scores].sort((a, b) => b - a));
      await page.screenshot({ path: testInfo.outputPath('strategies.png'), fullPage: true });
      await panel.getByTestId('option-horizon-short').click();
      await expect(panel).toContainText('近 5 日涨跌');
      await page.getByTestId('options-data-tab').click();
      await expect(page.getByRole('dialog')).toContainText('暂无期权数据');
      await page.getByTestId('options-strategies-tab').click();
      await expect(panel.getByTestId('option-horizon-short')).toHaveAttribute('aria-pressed', 'true');
      expect(requests.filter(url => url.includes('/daily-bars/'))).toHaveLength(1);
      await panel.getByRole('textbox', { name: '搜索期权玩法' }).fill('买入看涨');
      const strategy = panel.getByTestId('option-strategy-long-call');
      await expect(strategy).toBeVisible();
      await strategy.getByRole('button', { name: '查看 买入看涨 说明', exact: true }).click();
      const hint = page.getByRole('dialog', { name: '买入看涨说明', exact: true });
      await expect(hint).toContainText('结构：'); await expect(hint).toContainText('收益与损失：');
      await expect(hint).toContainText('时间流逝');
      await page.keyboard.press('Escape');
      await expect(page.getByRole('tab', { name: '期权', exact: true })).toBeVisible();
      expect(requests.some(url => url.includes('options-intelligence/'))).toBe(false);
      expect(requests.some(url => url.startsWith('POST '))).toBe(false);
      expect(errors).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      const overflow = await panel.evaluate(element => [...element.querySelectorAll('*')]
        .filter(child => child.clientWidth > 0 && child.scrollWidth > child.clientWidth + 2)
        .map(child => child.textContent?.slice(0, 40)));
      expect(overflow).toEqual([]);
    });
  }
}
test('US outside the stored options pool still has strategy scores and a no-data state', async ({ page }) => {
  const requests: string[] = [];
  await openOptions(page, { ...cn, code: 'JNJ.US', market: 'US', bars: { ...bars, symbol: 'JNJ.US', market: 'US' } }, requests);
  await expect(page.getByRole('dialog')).toContainText('暂无期权数据');
  expect(requests.some(url => url.startsWith('GET /api/v1/options-intelligence/JNJ.US'))).toBe(true);
  expect(requests.some(url => url.startsWith('POST '))).toBe(false);
});
const replayPath = process.env.FA_OPTIONS_REPLAY_FIXTURE;
const replay: Replay[] = replayPath ? JSON.parse(fs.readFileSync(replayPath, 'utf8')).samples : [];
for (const sample of replay) {
  test(`read-only production replay ${sample.code}`, async ({ page }, testInfo) => {
    const errors: string[] = [], requests: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    await openOptions(page, sample, requests);
    await expect(page.getByTestId('option-strategy-panel')).toContainText('2026-10-30');
    await expect(page.locator('[data-score]').first()).toBeVisible();
    if (!sample.options) await expect(page.getByRole('dialog')).toContainText('暂无期权数据');
    else {
      await page.getByTestId('options-data-tab').click();
      await expect(page.getByRole('dialog')).toContainText('证据');
    }
    expect(errors).toEqual([]);
    expect(requests.some(url => url.startsWith('POST '))).toBe(false);
    await page.screenshot({ path: testInfo.outputPath('production-replay.png'), fullPage: true });
  });
}
