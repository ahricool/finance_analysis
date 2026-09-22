import { mount, flushPromises } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import Page from '../IntradayConfirmationPage.vue';
import { intradayConfirmationApi as api } from '@/api/intradayConfirmation';
vi.mock('@/api/intradayConfirmation', () => ({ intradayConfirmationApi: { read: vi.fn(), run: vi.fn() } }));
vi.mock('@/composables/useAuth', () => ({ useAuth: () => ({ currentUser: { role: 'user' } }) }));
const snapshot = { market: 'US', tradeDate: '2026-09-21', candidateTradeDate: '2026-09-18', status: 'evaluated',
  generatedAt: '2026-09-21T14:00:00Z', frozenAt: '2026-09-21T13:25:00Z', warnings: [],
  summary: { total: 1, confirmed: 1, wait: 0, failed: 0 }, rulesNote: 'V1 启发式规则，未经回测验证',
  items: [{ code: 'ABC.US', name: 'ABC', candidateSource: 'trend', candidateTradeDate: '2026-09-18',
    candidateReason: ['昨日 CANDIDATE'], state: 'CONFIRMED', confirmationScore: 90, chaseRisk: 'HIGH',
    reasons: [{ code: 'vwap', text: '价格高于 VWAP' }], stateReasons: [], metrics: { return5M: .01, return15M: null,
      quoteTime: '2026-09-21T13:45:00Z', volumeRatio: 1.6 }, trend: { impact: 'intact' } }] };
describe('intraday confirmation page', () => {
  it('shows dates, candidate reasons, unavailable and independent high chase risk', async () => {
    vi.mocked(api.read).mockResolvedValue(snapshot as never);
    const wrapper = mount(Page);
    await flushPromises();
    expect(wrapper.text()).toContain('昨日 CANDIDATE');
    expect(wrapper.text()).toContain('2026-09-18');
    expect(wrapper.text()).toContain('CONFIRMED');
    expect(wrapper.text()).toContain('HIGH');
    expect(wrapper.text()).toContain('unavailable');
    expect(wrapper.text()).toContain('Yahoo 可能延迟');
    expect(wrapper.text()).not.toContain('运行确认任务');
    expect(api.run).not.toHaveBeenCalled();
    await wrapper.get('select[aria-label="状态"]').setValue('FAILED');
    await flushPromises();
    expect(api.read).toHaveBeenLastCalledWith('CN', 'FAILED', undefined);
    wrapper.unmount();
  });
  it('shows missed preopen freeze as an empty pool', async () => {
    vi.mocked(api.read).mockResolvedValue({ ...snapshot, status: 'not_frozen', items: [] } as never);
    const wrapper = mount(Page);
    await flushPromises();
    expect(wrapper.text()).toContain('开盘后不会根据涨幅补建候选');
    wrapper.unmount();
  });
});
