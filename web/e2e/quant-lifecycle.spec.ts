import { expect, test } from '@playwright/test';

for (const role of ['user', 'admin']) {
  test(`quant lifecycle navigation for ${role}`, async ({ page }) => {
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let body: unknown = [];
      if (path.endsWith('/auth/status')) body = { loggedIn: true, user: { uid: 1, username: 'Tester', role, extra: {} } };
      else if (path.endsWith('/quant/status')) body = {market:'US', universe:'us_quant', universeName:'美股研究池', memberCount: 503, latestAttempt:null};
      else if (path.endsWith('/dates')) body = {items:[]};
      else if (path.endsWith('/training/preflight')) {
        await route.fulfill({status:409,json:{detail:'历史不足：80交易日推理输入不能用于训练'}}); return;
      }
      else if (path.endsWith('/signals/ranking')) body = {market:'US',tradeDate:'2026-10-29',releaseId:3,items:Array.from({length:205},(_,i)=>({id:i,code:`TEST${i}.US`,name:`测试证券 ${i}`,market:'US',tradeDate:'2026-10-29',finalScore:100-i/3,universeRank:i+1,signal:'WATCH',reasons:[],scoreComponents:{}}))};
      await route.fulfill({json:body});
    });
    await page.goto('/research/quant/signals');
    await expect(page.getByTestId('quant-scope-description')).toContainText('503');
    await expect(page.getByRole('link', {name:'数据集',exact:true})).toHaveCount(0);
    await expect(page.getByText('共 205 个标的。', {exact:false})).toBeVisible();
    await page.getByPlaceholder('股票代码或名称').fill('DOES_NOT_EXIST');
    await expect(page.getByText('没有匹配的股票')).toBeVisible();
    await page.goto('/research/quant/datasets?market=US');
    if (role === 'user') {
      await expect(page).toHaveURL(/\/research\/quant\?market=US$/);
      await expect(page.getByRole('link', {name:'模型管理',exact:true})).toHaveCount(0);
    } else {
      await expect(page).toHaveURL(/\/research\/quant\/models\?market=US$/);
      await page.getByRole('button', {name:'创建训练实验',exact:true}).click();
      await page.getByRole('button', {name:'检查训练数据',exact:true}).click();
      await expect(page.getByText(/历史不足：80交易日/)).toBeVisible();
      await expect(page.getByRole('button', {name:'提交双模型训练',exact:true})).toBeDisabled();
      await page.setViewportSize({width:390,height:844});
      await expect(page.getByRole('button', {name:'提交双模型训练',exact:true})).toBeVisible();
    }
  });
}
