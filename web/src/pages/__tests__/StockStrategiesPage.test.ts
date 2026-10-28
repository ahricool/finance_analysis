import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import camelcaseKeys from 'camelcase-keys';
import { detail as rawDetail } from '../../../e2e/fixtures/stockStrategies';
import { tasksApi } from '@/api/tasks';
import { ref } from 'vue';
import StockStrategiesPage from '../StockStrategiesPage.vue';
import { stockStrategiesApi as api, type Detail, type Overview } from '@/api/stockStrategies';

vi.mock('@/api/stockStrategies', () => ({ stockStrategiesApi: { overview: vi.fn(), detail: vi.fn(), run: vi.fn() } }));
const auth = vi.hoisted(() => ({ role: 'user' }));
vi.mock('@/composables/useAuth', () => ({ useAuth: () => ({ currentUser: ref(auth) }) }));
vi.mock('@/api/tasks', () => ({ tasksApi: { getTaskRunDetail: vi.fn() } }));
const detailFixture = () => camelcaseKeys(structuredClone(rawDetail), { deep: true, exclude: [/\.(?:US|SH|SZ|BJ)$/] }) as unknown as Detail;
function fixture(market: 'CN' | 'US'): Overview {
  return { market, items: [{ strategy: { key: 'ma_dd30', name: `${market}测试策略`, slots: 1, atr: 0, version: '1' },
    latest: { tradeDate: '2026-10-19', dailyReturn: .01, totalReturn: .02, cagr: null, maxDrawdown: -.03, exposure: 1 },
    lastRun: { status: 'failed', tradeDate: '2026-10-20', reason: '等待缺失输入' }, status: 'failed' }] } as Overview;
}
async function setup() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/strategies', name: 'strategies', component: StockStrategiesPage },
    { path: '/strategies/:strategyKey', name: 'strategy-detail', component: StockStrategiesPage },
  ] });
  await router.push('/strategies?market=US'); await router.isReady();
  const wrapper = mount(StockStrategiesPage, { global: { plugins: [router] } });
  return { router, wrapper };
}

describe('stock strategy page', () => {
  beforeEach(() => { vi.clearAllMocks(); auth.role = 'user'; vi.spyOn(window, 'scrollTo').mockImplementation(() => {}); });
  it('shows failed date separately from the last successful return and preserves market in links', async () => {
    vi.mocked(api.overview).mockResolvedValue(fixture('US'));
    const { wrapper } = await setup(); await flushPromises();
    expect(wrapper.text()).toContain('运行失败');
    expect(wrapper.text()).toContain('2026-10-19');
    expect(wrapper.text()).toContain('2026-10-20：等待缺失输入');
    expect(wrapper.text()).toContain('+1.00%');
    expect(wrapper.find('a[href="/strategies/ma_dd30?market=US"]').exists()).toBe(true);
    expect(wrapper.text()).not.toContain('检查本市场');
    wrapper.unmount();
  });
  it('rejects old market responses after a fast market switch', async () => {
    let oldResolve: (r: Overview) => void = () => {};
    vi.mocked(api.overview).mockImplementation(market => market === 'US'
      ? new Promise(resolve => { oldResolve = resolve; }) : Promise.resolve(fixture('CN')));
    const { router, wrapper } = await setup();
    await router.push('/strategies?market=CN'); await flushPromises();
    oldResolve(fixture('US')); await flushPromises();
    expect(wrapper.text()).toContain('CN测试策略');
    expect(wrapper.text()).not.toContain('US测试策略');
    wrapper.unmount();
  });
  it('filters by name and status, sorts returns, and preserves query on detail and return', async () => {
    const data = fixture('US');
    data.items.push({ ...data.items[0]!, strategy: { ...data.items[0]!.strategy, key: 'second', name: '第二策略' }, status: 'success', latest: { ...data.items[0]!.latest!, totalReturn: .5 } });
    vi.mocked(api.overview).mockResolvedValue(data); vi.mocked(api.detail).mockResolvedValue(detailFixture());
    const { router, wrapper } = await setup(); await flushPromises();
    await router.replace('/strategies?market=US&sort=return_desc'); await flushPromises();
    expect(wrapper.findAll('[data-testid="strategy-row"]')[0]!.text()).toContain('第二策略');
    await router.replace('/strategies?market=US&search=测试&status=failed&sort=return_desc'); await flushPromises();
    expect(wrapper.findAll('[data-testid="strategy-row"]')).toHaveLength(1);
    await wrapper.find('[data-testid="strategy-row"] a').trigger('click'); await flushPromises();
    expect(router.currentRoute.value.query).toMatchObject({ search: '测试', status: 'failed', sort: 'return_desc' });
    await wrapper.findAll('a').find(a => a.text().includes('策略列表'))!.trigger('click'); await flushPromises();
    expect(wrapper.findAll('[data-testid="strategy-row"]')).toHaveLength(1); wrapper.unmount();
  });
  it('retains the current strategy while refreshing but clears it on strategy change', async () => {
    vi.mocked(api.overview).mockResolvedValue(fixture('US'));
    vi.mocked(api.detail).mockResolvedValueOnce(detailFixture());
    const { router, wrapper } = await setup(); await router.push('/strategies/ma_dd30?market=US'); await flushPromises();
    let finish: (d: Detail) => void = () => {};
    vi.mocked(api.detail).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    await wrapper.findAll('button').find(b => b.text().includes('刷新'))!.trigger('click');
    expect(wrapper.text()).toContain(rawDetail.strategy.name);
    vi.mocked(api.detail).mockRejectedValueOnce(new Error('unavailable'));
    await router.push('/strategies/other?market=US'); await flushPromises();
    expect(wrapper.text()).not.toContain(rawDetail.strategy.name);
    finish(detailFixture()); await flushPromises();
    expect(wrapper.text()).not.toContain(rawDetail.strategy.name); wrapper.unmount();
  });
  it('tracks an admin task and refreshes on terminal status', async () => {
    auth.role = 'admin'; vi.mocked(api.overview).mockResolvedValue(fixture('US'));
    vi.mocked(api.run).mockResolvedValue({ taskId: 'check-1' });
    vi.mocked(tasksApi.getTaskRunDetail).mockResolvedValue({ status: 'completed' } as Awaited<ReturnType<typeof tasksApi.getTaskRunDetail>>);
    const { wrapper } = await setup(); await flushPromises();
    await wrapper.findAll('button').find(b => b.text() === '检查本市场')!.trigger('click'); await flushPromises();
    expect(tasksApi.getTaskRunDetail).toHaveBeenCalledWith('check-1');
    expect(api.overview).toHaveBeenCalledTimes(2); expect(wrapper.text()).toContain('检查完成'); wrapper.unmount();
  });

  it('ignores a submitted task response after switching away and back to the same market', async () => {
    auth.role = 'admin'; vi.mocked(api.overview).mockImplementation(m => Promise.resolve(fixture(m)));
    let accept: (r: { taskId: string }) => void = () => {};
    vi.mocked(api.run).mockImplementation(() => new Promise(resolve => { accept = resolve; }));
    const { router, wrapper } = await setup(); await flushPromises();
    await wrapper.findAll('button').find(b => b.text() === '检查本市场')!.trigger('click');
    await router.push('/strategies?market=CN'); await flushPromises();
    await router.push('/strategies?market=US'); await flushPromises();
    accept({ taskId: 'old-task' }); await flushPromises();
    expect(tasksApi.getTaskRunDetail).not.toHaveBeenCalled(); wrapper.unmount();
  });

});
