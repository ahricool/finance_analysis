import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SignalEvaluationPage from '../SignalEvaluationPage.vue';

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
}));

vi.mock('@/api/signals', () => ({
  signalsApi: apiMocks,
}));

const signal = {
  id: 1,
  market: 'US' as const,
  code: 'NVDA',
  name: null,
  signalType: 'custom_signal',
  signalVersion: 'v2',
  direction: 'bullish' as const,
  signalAt: '2026-06-30T14:34:00Z',
  signalPrice: 158.2,
  evaluation: {
    '30m': {
      price: 159.1,
      returnPct: 0.5689,
      maxReturnPct: 0.92,
      minReturnPct: -0.21,
      evaluatedAt: '2026-06-30T15:04:00Z',
    },
    '1h': { status: 'not_applicable' as const, reason: 'non_intraday_signal' },
    '3d': {},
  },
  createdAt: '2026-06-30T14:35:10Z',
  updatedAt: '2026-07-01T21:00:00Z',
};

describe('SignalEvaluationPage', () => {
  beforeEach(() => {
    apiMocks.list.mockImplementation(async (query) => ({
      items: [signal],
      total: 40,
      page: query?.page ?? 1,
      pageSize: 20,
    }));
    apiMocks.get.mockResolvedValue(signal);
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
  });

  it('loads records and renders all evaluation states in a mobile-readable grid', async () => {
    const wrapper = mount(SignalEvaluationPage, { attachTo: document.body });
    await flushPromises();

    expect(apiMocks.list).toHaveBeenCalledWith(expect.objectContaining({ page: 1, pageSize: 20 }));
    expect(wrapper.text()).toContain('custom_signal');
    expect(wrapper.text()).toContain('看多');
    expect(wrapper.text()).toContain('+0.57%');
    expect(wrapper.text()).toContain('不适用');
    expect(wrapper.text()).toContain('待评估');
    expect(wrapper.text()).toContain('—');
    expect(wrapper.get('[data-testid="signal-returns-grid"]').classes()).toContain('grid-cols-2');
  });

  it('opens the shared drawer and shows detailed period metrics', async () => {
    const wrapper = mount(SignalEvaluationPage, { attachTo: document.body });
    await flushPromises();
    await wrapper.get('button[type="button"].text-primary').trigger('click');
    await flushPromises();

    expect(apiMocks.get).toHaveBeenCalledWith(1);
    expect(document.body.textContent).toContain('信号评估详情');
    expect(document.body.textContent).toContain('目标价格');
    expect(document.body.textContent).toContain('+0.92%');
    expect(document.body.textContent).toContain('-0.21%');
    expect(document.body.textContent).toContain('非盘中信号');
  });

  it('submits filters from page one and preserves them while paging', async () => {
    const wrapper = mount(SignalEvaluationPage, { attachTo: document.body });
    await flushPromises();
    const selects = wrapper.findAll('select');
    await selects[0].setValue('US');
    await selects[1].setValue('bullish');
    const inputs = wrapper.findAll('input');
    await inputs[0].setValue('relative_strength_breakout');
    await inputs[1].setValue('NVDA');
    await wrapper.get('form').trigger('submit');
    await flushPromises();

    expect(apiMocks.list).toHaveBeenLastCalledWith(
      expect.objectContaining({
        page: 1,
        market: 'US',
        direction: 'bullish',
        signalType: 'relative_strength_breakout',
        keyword: 'NVDA',
      }),
    );

    const pageTwo = wrapper.findAll('button').find((button) => button.text() === '2');
    expect(pageTwo).toBeDefined();
    await pageTwo!.trigger('click');
    await flushPromises();
    expect(apiMocks.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2, market: 'US', keyword: 'NVDA' }),
    );
  });

  it('renders empty and error states', async () => {
    apiMocks.list.mockResolvedValueOnce({ items: [], total: 0, page: 1, pageSize: 20 });
    const emptyWrapper = mount(SignalEvaluationPage);
    await flushPromises();
    expect(emptyWrapper.get('[data-testid="signal-empty-state"]').text()).toContain('暂无信号记录');
    emptyWrapper.unmount();

    apiMocks.list.mockRejectedValueOnce(new Error('network failed'));
    const errorWrapper = mount(SignalEvaluationPage);
    await flushPromises();
    expect(errorWrapper.get('[role="alert"]').text()).toContain('network failed');
  });
});
