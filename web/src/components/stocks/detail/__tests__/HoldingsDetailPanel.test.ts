import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import HoldingsDetailPanel from '../HoldingsDetailPanel.vue';
import { holdingsApi, tradeEngineApi, type HoldingsSummary, type PortfolioPosition } from '@/api/holdings';
vi.mock('@/api/holdings', () => ({
  holdingsApi: { summary: vi.fn(), operations: vi.fn(), markers: vi.fn(), updatePosition: vi.fn() },
  tradeEngineApi: { positions: vi.fn() },
}));
const position = (id = 1, accountId = 10, symbol = 'AAPL.US'): PortfolioPosition => ({ id, accountId, symbol, market: 'US', assetType: 'STOCK', quantity: '12', averageCost: '100', tradeEngineEnabled: true });
const summary = (positions = [position()]): HoldingsSummary => ({ market: 'US', accounts: [{ id: 10, name: '美股账户', market: 'US', currency: 'USD', cash: '100' }, { id: 20, name: '第二账户', market: 'US', currency: 'USD', cash: '200' }], positions, cash: '100', marketValue: '1200', totalAsset: '1300', grossExposure: null });
const stubs = { ResearchEvidence: true, DailyKLineCard: true };
function mountPanel(context?: { accountId?: number; positionId?: number }) {
  return mount(HoldingsDetailPanel, { props: { symbol: 'AAPL.US', market: 'US', context }, global: { stubs } });
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(holdingsApi.summary).mockResolvedValue(summary());
  vi.mocked(holdingsApi.operations).mockResolvedValue([]);
  vi.mocked(holdingsApi.markers).mockResolvedValue([]);
  vi.mocked(tradeEngineApi.positions).mockResolvedValue([]);
});
describe('HoldingsDetailPanel', () => {
  it('loads the same holding from any entrypoint and preserves operations and BST', async () => {
    vi.mocked(holdingsApi.operations).mockResolvedValue([{ executedAt: '2026-10-01', side: 'BUY', quantity: '12', price: '100' }]);
    vi.mocked(holdingsApi.markers).mockResolvedValue([{ timestamp: '2026-10-01T10:00:00Z', type: 'B', operations: [] }]);
    const wrapper = mountPanel(); await flushPromises();
    expect(wrapper.text()).toContain('数量 12');
    expect(wrapper.text()).toContain('美股账户');
    expect(wrapper.text()).toContain('2026-10-01 BUY 12 @100');
    expect(wrapper.findComponent({ name: 'DailyKLineCard' }).props('markers')).toEqual([{ timestamp: Date.parse('2026-10-01T10:00:00Z'), type: 'B', operations: [] }]);
    wrapper.unmount();
  });
  it('pins the source account/position and never falls back to a different account', async () => {
    vi.mocked(holdingsApi.summary).mockResolvedValue(summary([position(1, 10), position(2, 20)]));
    const wrapper = mountPanel({ accountId: 20, positionId: 2 }); await flushPromises();
    expect(holdingsApi.operations).toHaveBeenCalledWith(2);
    expect(wrapper.text()).toContain('第二账户');
    await wrapper.setProps({ context: { accountId: 30, positionId: 3 } }); await flushPromises();
    expect(wrapper.text()).toContain('暂无该证券持仓');
    expect(holdingsApi.operations).not.toHaveBeenCalledWith(1);
    wrapper.unmount();
  });
  it('lets cross-entry users choose between existing holding accounts', async () => {
    vi.mocked(holdingsApi.summary).mockResolvedValue(summary([position(1, 10), position(2, 20)]));
    const wrapper = mountPanel(); await flushPromises();
    await wrapper.get('[data-testid="holding-account"]').setValue(2); await flushPromises();
    expect(holdingsApi.operations).toHaveBeenLastCalledWith(2);
    wrapper.unmount();
  });
  it('updates the selected reminder and notifies the source list', async () => {
    vi.mocked(holdingsApi.updatePosition).mockResolvedValue({ ...position(), tradeEngineEnabled: false });
    const wrapper = mountPanel(); await flushPromises();
    await wrapper.get('[data-testid="trade-engine-enabled"]').setValue(false); await flushPromises();
    expect(holdingsApi.updatePosition).toHaveBeenCalledWith(1, { tradeEngineEnabled: false });
    expect(wrapper.emitted('updated')).toHaveLength(1);
    expect((wrapper.get('input').element as HTMLInputElement).checked).toBe(false);
    wrapper.unmount();
  });
  it('keeps an engine failure separate from loaded holdings and retries it', async () => {
    vi.mocked(tradeEngineApi.positions).mockRejectedValueOnce(new Error('engine unavailable'));
    const wrapper = mountPanel(); await flushPromises();
    expect(wrapper.text()).toContain('数量 12');
    expect(wrapper.text()).toContain('Trade Engine 建议读取失败');
    await wrapper.findAll('button').find(button => button.text() === '重试建议')!.trigger('click'); await flushPromises();
    expect(wrapper.text()).not.toContain('Trade Engine 建议读取失败');
    wrapper.unmount();
  });
  it('does not let late symbol responses replace the new identity', async () => {
    let finish!: (data: HoldingsSummary) => void;
    vi.mocked(holdingsApi.summary).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = mountPanel();
    vi.mocked(holdingsApi.summary).mockResolvedValue(summary([position(3, 10, 'MSFT.US')]));
    await wrapper.setProps({ symbol: 'MSFT.US' }); await flushPromises();
    finish(summary()); await flushPromises();
    expect(holdingsApi.operations).toHaveBeenCalledWith(3);
    expect(holdingsApi.operations).not.toHaveBeenCalledWith(1);
    expect(wrapper.findComponent({ name: 'DailyKLineCard' }).props('symbol')).toBe('MSFT.US');
    wrapper.unmount();
  });
  it('ignores a pending mutation after closing', async () => {
    let finish!: (data: PortfolioPosition) => void;
    vi.mocked(holdingsApi.updatePosition).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = mountPanel(); await flushPromises();
    await wrapper.get('input').setValue(false); wrapper.unmount();
    finish({ ...position(), tradeEngineEnabled: false }); await flushPromises();
    expect(wrapper.emitted('updated')).toBeUndefined();
  });
  it('shows neutral unsupported and empty states without invented values', async () => {
    const wrapper = mountPanel(); await flushPromises();
    await wrapper.setProps({ market: 'HK' }); await flushPromises();
    expect(wrapper.text()).toContain('暂不支持持仓管理');
    expect(holdingsApi.summary).toHaveBeenCalledTimes(1);
    vi.mocked(holdingsApi.summary).mockResolvedValue(summary([]));
    await wrapper.setProps({ market: 'US' }); await flushPromises();
    expect(wrapper.text()).toContain('暂无该证券持仓');
    expect(wrapper.text()).not.toContain('数量 0'); wrapper.unmount();
  });
  it('does not reload equal source context during unrelated parent rerenders', async () => {
    const wrapper = mountPanel({ accountId: 10, positionId: 1 }); await flushPromises();
    await wrapper.setProps({ context: { accountId: 10, positionId: 1 } }); await flushPromises();
    expect(holdingsApi.summary).toHaveBeenCalledTimes(1);
    expect(holdingsApi.operations).toHaveBeenCalledTimes(1); wrapper.unmount();
  });

});
