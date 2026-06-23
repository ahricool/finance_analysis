import { describe, expect, it } from 'vitest';
import router, { resolveDocumentTitle } from '../index';

describe('router document titles', () => {
  it.each([
    ['/', 'Finance Analysis'],
    ['/calendar', '日历记录 - Finance Analysis'],
    ['/watch-list', '自选股 - Finance Analysis'],
    ['/stock-list', '持仓股 - Finance Analysis'],
    ['/chat', '问股 - Finance Analysis'],
    ['/backtest', '策略回测 - Finance Analysis'],
    ['/profile', '个人中心 - Finance Analysis'],
    ['/tasks', '任务中心 - Finance Analysis'],
    ['/tasks/scheduled', '任务中心 - Finance Analysis'],
    ['/tasks/runs', '任务中心 - Finance Analysis'],
    ['/login', '登录 - Finance Analysis'],
    ['/missing-page', '页面未找到 - Finance Analysis'],
  ])('resolves %s to %s', (path, expectedTitle) => {
    expect(resolveDocumentTitle({ matched: router.resolve(path).matched })).toBe(expectedTitle);
  });
});
