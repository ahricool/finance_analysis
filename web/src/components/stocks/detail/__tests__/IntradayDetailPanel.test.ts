import { beforeEach, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { intradayConfirmationApi as api, type Confirmation } from '@/api/intradayConfirmation';
import IntradayDetailPanel from '../IntradayDetailPanel.vue';

vi.mock('@/api/intradayConfirmation', () => ({ intradayConfirmationApi: { detail: vi.fn(), evaluations: vi.fn() } }));
const confirmation: Confirmation = {
  code: 'TEST.US', name: '测试', candidateSource: 'trend', candidateTradeDate: '2026-10-30',
  candidateReason: [], sourceGeneratedAt: '2026-10-30T12:40:00Z', currentStatus: 'ACTIVE',
  state: 'CONFIRMED', confirmationScore: 90, availableScoreWeight: 100, chaseRisk: 'LOW',
  reasons: [], stateReasons: [], trend: {}, firstConfirmedAt: null, failedAt: null,
  generatedAt: null, currentPriceRecovered: false,
  conditions: { openingBreakout: false, ma5Pullback: true, priceSetup: true },
  metrics: { pullbackMa5: 100, pullbackMa10: 99, pullbackTouchTime: '2026-11-02T14:00:00Z',
    pullbackReclaimTime: '2026-11-02T14:10:00Z' },
};
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.detail).mockResolvedValue(confirmation);
  vi.mocked(api.evaluations).mockResolvedValue({ items: [] });
});

it('explains the alternative routes and exposes saved MA and ordered time evidence', async () => {
  const wrapper = mount(IntradayDetailPanel, { props: { symbol: 'TEST.US', market: 'US' },
    global: { stubs: { IntradaySourceEvidence: true } } });
  await flushPromises();
  const evidence = wrapper.get('[data-testid="intraday-pullback-evidence"]');
  expect(evidence.text()).toContain('突破与回踩为并列路线');
  expect(evidence.text()).toContain('MA5 100.00');
  expect(evidence.text()).toContain('MA10 99.00');
  expect(evidence.text()).toContain('两次稳定评估');
  expect(wrapper.text()).toContain('突破或回踩任一路线满足');
  expect(wrapper.text()).not.toContain('暂无分类');
  wrapper.unmount();
});

it('does not invent pullback evidence for historical rules', async () => {
  vi.mocked(api.detail).mockResolvedValue({ ...confirmation, conditions: { openingBreakout: true }, metrics: {} });
  const wrapper = mount(IntradayDetailPanel, { props: { symbol: 'TEST.US', market: 'US' },
    global: { stubs: { IntradaySourceEvidence: true } } });
  await flushPromises();
  expect(wrapper.find('[data-testid="intraday-pullback-evidence"]').exists()).toBe(false);
  wrapper.unmount();
});
