import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import type { SignalEvaluation } from '@/api/signalCenter';
import Evaluation from '../SignalEvaluation.vue';
import { horizonText, returnClass } from '../evaluation';

const evaluation: SignalEvaluation = {
  method: 'next_session_open_v1', status: 'partial', reason: 'missing_or_invalid_bars',
  entryDate: '2026-09-21', entryPrice: 100, asOf: '2026-09-24', observedSessions: 3,
  missingDates: ['2026-09-22'], mfe: null, mae: null, maxDrawdownClose: null, evaluatedAt: '2026-09-24T20:00:00Z',
  horizons: [
    { days: 1, targetDate: '2026-09-21', value: .1, status: 'available' },
    { days: 3, targetDate: '2026-09-23', value: null, status: 'missing' },
    { days: 5, targetDate: '2026-09-25', value: null, status: 'pending' },
    { days: 10, targetDate: '2026-10-02', value: null, status: 'pending' },
  ],
};
describe('signal forward evaluation', () => {
  it('distinguishes pending, missing, no-trade and zero returns', () => {
    expect(horizonText(evaluation, 1)).toBe('+10.00%');
    expect(horizonText(evaluation, 3)).toBe('缺行情');
    expect(horizonText(evaluation, 5)).toBe('未到期');
    expect(horizonText({ ...evaluation, status: 'not_applicable' }, 1)).toBe('—');
    expect(horizonText({ ...evaluation, horizons: [{ days: 1, targetDate: '', status: 'available', value: 0 }] }, 1)).toBe('0.00%');
    expect(returnClass(-.1)).toBe('text-market-down');
    expect(returnClass(.1)).toBe('text-market-up');
  });
  it('displays exact basis, missing dates and observational limitations', () => {
    const wrapper = mount(Evaluation, { props: { evaluation } });
    expect(wrapper.text()).toContain('2026-09-21 开盘 100.00');
    expect(wrapper.text()).toContain('2026-09-22');
    expect(wrapper.text()).toContain('缺行情');
    expect(wrapper.text()).toContain('A股1D仅作观察');
    expect(wrapper.text()).toContain('收盘最大回撤');
  });
});
