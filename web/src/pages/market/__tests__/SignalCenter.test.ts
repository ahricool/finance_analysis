import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import SignalCenterPage from '../SignalCenterPage.vue';
import { signalCenterApi as api, type SignalDetail } from '@/api/signalCenter';
vi.mock('@/api/signalCenter', () => ({ signalCenterApi: { daily: vi.fn(), history: vi.fn(), detail: vi.fn() } }));
const signal: SignalDetail = { market: 'CN', signalDate: '2026-09-22', status: 'completed', selectedSymbol: null,
  decision: 'NO_TRADE', confidence: 'medium', createdAt: '2026-09-22T12:00:00Z', completedAt: '2026-09-22T12:01:00Z',
  analysis: { thesis: '冲突明显，不交易', positiveSignals: [], risks: ['追高'], invalidations: [] },
  candidateSnapshot: { capturedAt: '2026-09-22T12:00:00Z', candidates: [{ symbol: '600000.SH' }], sourceAvailability: { trend: { status: 'available', dataAsOf: '2026-09-22', generatedAt: '2026-09-22T11:00:00Z' } } },
  model: 'test', promptVersion: 'v1', error: null };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.daily).mockResolvedValue({ items: [signal], requestedDates: { CN: '2026-09-22', US: '2026-09-21' } }); vi.mocked(api.history).mockResolvedValue([signal]); vi.mocked(api.detail).mockResolvedValue(signal); });
describe('Signal Center page', () => {
  it('shows NO_TRADE distinctly from a missing market and uses persisted historical detail', async () => {
    const wrapper = mount(SignalCenterPage);
    await flushPromises();
    expect(wrapper.text()).toContain('当日不交易');
    expect(wrapper.text()).toContain('美股 · 2026-09-21');
    expect(wrapper.text()).toContain('当日尚无信号记录');
    expect(wrapper.text()).toContain('冲突明显，不交易');
    await wrapper.get('[aria-label="查看 2026-09-22 CN 信号"]').trigger('click');
    await flushPromises();
    expect(api.detail).toHaveBeenCalledWith('CN', '2026-09-22');
    wrapper.unmount();
  });
  it('displays failure without presenting it as NO_TRADE', async () => {
    vi.mocked(api.daily).mockResolvedValue({ items: [{ ...signal, status: 'failed', decision: null, confidence: null, analysis: null }], requestedDates: { CN: '2026-09-22', US: '2026-09-21' } });
    vi.mocked(api.history).mockResolvedValue([]);
    const wrapper = mount(SignalCenterPage); await flushPromises();
    expect(wrapper.text()).toContain('分析失败，未产生信号');
    expect(wrapper.text()).not.toContain('当日不交易');
    wrapper.unmount();
  });
});
