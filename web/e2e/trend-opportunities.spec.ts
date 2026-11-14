import { test, expect, type Page } from '@playwright/test';

async function setup(page: Page) {
  const requested: string[] = [];
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    requested.push(path);
    if (path.includes('/event-study') || path.endsWith('/transitions')) return route.fulfill({status:504,json:{detail:'upstream timeout'}});
    const day = '2026-11-13';
    const summary = {market:'CN', trade_date:day, market_regime:'RISK_ON', market_score:75, universe_size:100, data_ready_count:100, data_coverage:1, rankable_count:100, candidate_count:5, warnings:[], features:{}, score_breakdown:{}};
    let body = {};
    if(path.endsWith('/auth/status')) body={loggedIn:true,user:{uid:1,username:'Research',role:'user',extra:{}}};
    else if(path.endsWith('/preview/status')) {await route.fulfill({status:404,json:{detail:'no preview'}});return;}
    else if(path.endsWith('/status')) body={...summary, available:true, generated_at:day+'T10:00:00Z'};
    else if(path.endsWith('/dates')) body={market:'CN',latest:day,items:[day]};
    else if(path.endsWith('/ranking/table')) body={...summary,table:{columns:['code','name','rank','state','alpha_score'],feature_columns:[],rows:[['000001.SZ','研究样本',1,'TRENDING',80]]},changes:null,candidates:[]};
    else if(path.endsWith('/opportunities')) {
      const items=Array.from({length:13},(_,i)=>{
        const b={structure_id:'shape'+i,kind:i%2?'vcp':'flat_base',rule_version:'ohlcv_opportunity_v1',status:i===12?'NEAR_TRIGGER':'CONFIRMED',quality_score:86-i,trigger:100,invalidation:96,support:96,distance_pct:.012,distance_atr:.4,first_confirmed_at:day,discovered_at:'2026-11-10',start_date:'2026-10-01',end_date:'2026-11-12',data_as_of:day,anchor_date:day,anchor_close:101.2,preview:false,fresh:true,reason:'平台边界已冻结，收盘突破与量能条件满足',unmet:[],points:[],background_periods:[10]};
        return {code:String(600001+i)+'.SH',name:['结构研究样本','稳健趋势样本','收缩波段样本'][i%3]+i,primary:i===12?null:b,display:b,branches:[b],history_status:'complete',data_as_of:day};
      });
      body={items,generated_at:day+'T10:00:00Z',trade_date:day,status:'available',scanned_count:100,covered_count:100,candidate_count:12,candidate_limit:40};
    }
    else if(path.includes('/daily-bars/')) body={symbol:path.split('/').pop(),items:Array.from({length:90},(_,i)=>{const d=new Date(Date.UTC(2026,7,17+i));return {trade_date:d.toISOString().slice(0,10),open:99+i*.025,high:101+i*.025,low:98+i*.025,close:99.8+i*.025,volume:1000};})};
    else if(path.endsWith('/classification')) body={memberships:{indices:[],industries:[]},etf_proxies:[]};
    else if(path.endsWith('/breadth-history')||path.endsWith('/state-history')) body={...summary,dates:[],points:[],items:[],official_count:0};
    else body={...summary,items:[],dates:[]};
    await route.fulfill({json:body});
  });
  await page.goto('http://127.0.0.1:4173/research/trend-following');
  await page.getByTestId('trend-opportunities').waitFor();
  await page.getByTestId('trend-opportunities').scrollIntoViewIfNeeded();
  return requested;

}

for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  test(`buying opportunities remain usable at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(theme => localStorage.setItem('theme', theme), width % 2 ? 'dark' : 'light');
    const requested = await setup(page);
    await expect(page.getByTestId('trend-row')).toContainText('研究样本');
    const card = page.getByTestId('trend-opportunities');
    await expect(card.getByText('12 只证券 · 同票合并 · 每页 10 只')).toBeVisible();
    await card.getByRole('button', { name: '分支质量', exact: true }).click();
    await card.getByRole('button', { name: '分支质量', exact: true }).click();
    await expect(card.locator('tbody tr').first()).toContainText('600012.SH');
    await card.getByRole('textbox', { name: '搜索买点' }).fill('600001');
    const opportunityRequests = requested.filter(path => path.endsWith('/opportunities')).length;
    await page.getByTestId('trend-analysis').getByRole('button', { name: '20日', exact: true }).click();
    await expect(page.getByTestId('trend-analysis').getByRole('button', { name: '20日', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(card.getByRole('textbox', { name: '搜索买点' })).toHaveValue('600001');
    expect(requested.filter(path => path.endsWith('/opportunities')).length).toBe(opportunityRequests);
    expect(requested.filter(path => path.includes('/event-study') || path.endsWith('/transitions'))).toEqual([]);
    await expect(page.getByText('连接上游服务超时', {exact:true})).toHaveCount(0);
    await card.getByRole('button', { name: '展开 结构研究样本0 买点证据' }).click();
    await expect(card.locator('canvas').first()).toBeVisible();
    await card.getByRole('button', { name: '隐藏后台结构' }).click();
    await expect(card.getByRole('button', { name: '显示后台结构' })).toBeVisible();
    const download = page.waitForEvent('download');
    await card.getByRole('button', { name: '导出筛选结果' }).click();
    expect((await download).suggestedFilename()).toMatch(/买点机会.*xlsx$/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    expect(errors).toEqual([]);
  });
}
