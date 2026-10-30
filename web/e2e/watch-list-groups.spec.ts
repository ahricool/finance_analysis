import { expect, test } from '@playwright/test';

for (const width of [390, 768, 1024, 1280, 1440, 1920]) {
  test(`watch-list groups, empty states and dialogs at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    const tags = Array.from({ length: 16 }, (_, id) => ({ id: id + 1, name: `分组标签${id + 1}` }));
    const rows = [
      { id: 1, code: '600519.SH', name: '贵州茅台', market_type: 'CN', tags: tags.slice(0, 5) },
      { id: 2, code: 'AAPL.US', name: 'Apple', market_type: 'US', tags: [] },
    ].map(row => ({ ...row, notes: '保留备注', is_favorite: false, created_at: '2026-10-14', updated_at: '2026-10-14' }));
    const requests: URL[] = [];
    const sockets: URL[] = [];
    await page.routeWebSocket('**/api/v1/market-data/ws*', socket => {
      sockets.push(new URL(socket.url()));
      socket.send(JSON.stringify({ type: 'quotes', generated_at: 'now', quotes: [] }));
    });
    await page.route('**/api/v1/**', route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/v1/auth/status') return route.fulfill({ json: {
        loggedIn: true, user: { uid: 1, username: 'Tester', role: 'user', extra: {} },
      } });
      if (url.pathname === '/api/v1/watch-list/tags') return route.fulfill({ json: tags });
      if (url.pathname === '/api/v1/watch-list') {
        requests.push(url);
        const all = rows.filter(row => row.market_type === url.searchParams.get('market'));
        const tag = url.searchParams.get('tag_id');
        const items = all.filter(row => tag ? row.tags.some(t => t.id === Number(tag))
          : url.searchParams.get('ungrouped') === 'true' ? !row.tags.length : true);
        return route.fulfill({ json: { items, total: all.length } });
      }
      return route.fulfill({ json: {} });
    });
    await page.goto('/market/watch-list');
    await expect(page.getByTestId('tag-filters').getByRole('button').first()).toHaveText('全部');
    await expect(page.getByTestId('global-market-switch')).toHaveAttribute('aria-checked', 'false');
    await expect(page.getByTestId('stock-tags')).toContainText('分组标签5');
    await page.getByRole('button', { name: '自选股操作', exact: true }).click();
    await page.getByRole('menuitem', { name: '编辑', exact: true }).click();
    const edit = page.getByRole('dialog');
    await expect(edit.getByText('分组标签', { exact: true })).toBeVisible();
    await edit.getByPlaceholder('搜索或输入新标签名称').fill('新标签草稿');
    await edit.getByRole('button', { name: '创建并选中「新标签草稿」' }).click();
    await expect(edit.getByRole('button', { name: '移除标签 新标签草稿' })).toBeVisible();
    await edit.getByRole('button', { name: '取消', exact: true }).click();
    await expect(page.getByTestId('tag-filters')).not.toContainText('新标签草稿');
    await page.getByTestId('tag-filters').getByRole('button', { name: '分组标签16', exact: true }).click();
    await expect(page.getByText('当前分组暂无自选股', { exact: true })).toBeVisible();
    await expect.poll(() => requests.at(-1)?.searchParams.get('tag_id')).toBe('16');
    await expect.poll(() => sockets.at(-1)?.searchParams.get('tag_id')).toBe('16');
    await page.getByTestId('global-market-switch').click();
    await expect(page.getByText('当前分组暂无自选股', { exact: true })).toBeVisible();
    await expect.poll(() => sockets.at(-1)?.searchParams.get('market')).toBe('US');
    await expect(page.getByTestId('tag-filters').getByRole('button', { name: '分组标签16', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await page.getByTestId('tag-filters').getByRole('button', { name: '全部', exact: true }).click();
    await expect(page.getByRole('table')).toContainText('Apple');
    await page.getByRole('button', { name: '管理标签', exact: true }).click();
    await expect(page.getByRole('dialog').getByTestId('tag-manager-list')).toContainText('分组标签16');
    await page.getByRole('dialog').getByRole('button', { name: 'Close' }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`watch-list-${width}.png`), fullPage: true });
    expect(errors).toEqual([]);
  });
}
