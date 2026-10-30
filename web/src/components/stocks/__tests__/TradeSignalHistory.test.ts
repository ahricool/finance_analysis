import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
import TradeSignalHistory from '../TradeSignalHistory.vue';
const api = vi.hoisted(() => ({ signals: vi.fn() }));
vi.mock('@/api/holdings', () => ({ tradeEngineApi: api }));
const signal = { id: 1, symbol: '600519.SH', positionId: '11', evaluatedAt: '2026-09-17T10:00:00Z', action: 'REDUCE', strategyKey: 'market_llm', strategyVersion: '1', suggestedTargetQuantity: '5', reason: '当时风险偏高', evidence: { currentQuantity: '10', targetQuantity: '5', portfolioReason: '降低集中度' } };
const props = { symbol: '600519.SH', market: 'CN', positionId: 11 };
beforeEach(() => { vi.resetAllMocks(); api.signals.mockResolvedValue([signal, { ...signal, id: 2, positionId: '99', reason: '其他持仓' }]); });
it('preserves stored historical evidence and filters unrelated positions', async () => {
  const wrapper = mount(TradeSignalHistory, { props }); await flushPromises();
  expect(api.signals).toHaveBeenCalledWith('CN', '11');
  expect(wrapper.text()).toContain('当时风险偏高');
  expect(wrapper.text()).toContain('当时持仓 10 → 目标 5');
  expect(wrapper.text()).toContain('降低集中度');
  expect(wrapper.text()).not.toContain('其他持仓'); wrapper.unmount();
});
it('discards old account responses and retries a failed signal request', async () => {
  let finish!: (rows: unknown[]) => void;
  api.signals.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const wrapper = mount(TradeSignalHistory, { props });
  api.signals.mockRejectedValueOnce(new Error('offline'));
  await wrapper.setProps({ positionId: 12 }); await flushPromises();
  finish([signal]); await flushPromises();
  expect(wrapper.text()).not.toContain('当时风险偏高');
  api.signals.mockResolvedValueOnce([{ ...signal, positionId: '12' }]);
  await wrapper.findAll('button').find(button => button.text() === '重试历史建议')!.trigger('click'); await flushPromises();
  expect(wrapper.text()).toContain('当时风险偏高'); wrapper.unmount();
});
it('does not request private signals without a position or for HK', async () => {
  const wrapper = mount(TradeSignalHistory, { props: { symbol: '600519.SH', market: 'CN' } }); await flushPromises();
  await wrapper.setProps({ market: 'HK', positionId: 11 }); await flushPromises();
  expect(api.signals).not.toHaveBeenCalled(); wrapper.unmount();
});
