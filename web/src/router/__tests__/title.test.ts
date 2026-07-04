import { describe, expect, it } from 'vitest';
import router, { resolveDocumentTitle } from '../index';

describe('router document titles', () => {
  it.each([
    ['/', 'Finance Analysis'],
    ['/calendar', '日历记录 - Finance Analysis'],
    ['/market/watch-list', '自选股 - Finance Analysis'],
    ['/market/holdings', '持仓股 - Finance Analysis'],
    ['/market/signals', '信号评估 - Finance Analysis'],
    ['/market/backtests', '策略回测 - Finance Analysis'],
    ['/market/backtests/123', '回测详情 - Finance Analysis'],
    ['/market/quant', '量化研究 - Finance Analysis'],
    ['/market/quant/signals', '模型选股 - Finance Analysis'],
    ['/market/quant/signals/NVDA.US', '选股详情 - Finance Analysis'],
    ['/market/quant/models', '量化模型 - Finance Analysis'],
    ['/market/quant/events', '市场事件 - Finance Analysis'],
    ['/market/quant/portfolios', '组合建议 - Finance Analysis'],
    ['/chat', '问股 - Finance Analysis'],
    ['/profile', '个人中心 - Finance Analysis'],
    ['/tasks', '任务中心 - Finance Analysis'],
    ['/tasks/scheduled', '任务中心 - Finance Analysis'],
    ['/tasks/runs', '任务中心 - Finance Analysis'],
    ['/login', '登录 - Finance Analysis'],
    ['/missing-page', '页面未找到 - Finance Analysis'],
  ])('resolves %s to %s', (path, expectedTitle) => {
    expect(resolveDocumentTitle({ matched: router.resolve(path).matched })).toBe(expectedTitle);
  });

  it('does not register the removed top-level stock routes', () => {
    expect(router.hasRoute('watch-list')).toBe(false);
    expect(router.hasRoute('stock-list')).toBe(false);
    expect(router.resolve('/watch-list').name).toBe('not-found');
    expect(router.resolve('/stock-list').name).toBe('not-found');
  });
});
