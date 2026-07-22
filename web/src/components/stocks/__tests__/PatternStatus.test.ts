import type { RealtimePatternState } from '@/api/realtimeMarket';
import { mount } from '@vue/test-utils';
import { afterEach, describe, expect, it } from 'vitest';
import PatternStatus from '../PatternStatus.vue';

function pattern(overrides: Partial<NonNullable<RealtimePatternState['signal']>> = {}): RealtimePatternState {
  return {
    timeframe: '1m',
    status: 'active',
    trading_date: '2026-07-22',
    bar_time: '2026-07-22T14:36:00Z',
    signal: {
      timeframe: '1m',
      pattern_type: 'failed_breakout_reclaim',
      pattern_name: '假突破前高回收',
      direction: 'bullish_to_bearish',
      stage: 'confirmed',
      quality_score: 84,
      occurred_at: '2026-07-22T14:31:00Z',
      confirmed_at: '2026-07-22T14:33:00Z',
      trading_date: '2026-07-22',
      trade_session: 'Intraday',
      bars_ago: 2,
      session_minutes_ago: 2,
      reference_level: 132.5,
      invalidation_price: 132.7,
      reasons: ['突破前高后快速收回', '跌破回收结构低点'],
      confirmed: true,
      ...overrides,
    },
  };
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('PatternStatus', () => {
  it.each([
    ['bearish_to_bullish', 'warning', '空转多预警', 'text-red-500'],
    ['bearish_to_bullish', 'confirmed', '空转多确认', 'text-red-500'],
    ['bullish_to_bearish', 'warning', '多转空预警', 'text-emerald-500'],
    ['bullish_to_bearish', 'confirmed', '多转空确认', 'text-emerald-500'],
    ['bullish_continuation', 'forming', '多头整理', 'text-amber-500'],
    ['bearish_continuation', 'forming', '空头整理', 'text-amber-500'],
  ] as const)('renders %s %s consistently', (direction, stage, text, color) => {
    const wrapper = mount(PatternStatus, { props: { pattern: pattern({ direction, stage, confirmed: stage === 'confirmed' }) } });
    expect(wrapper.text()).toContain(text);
    expect(wrapper.get('span.flex').classes()).toContain(color);
  });

  it.each([
    [0, '刚刚'],
    [1, '1分钟前'],
    [7, '7分钟前'],
  ] as const)('formats age from confirmed bar count', (barsAgo, text) => {
    const wrapper = mount(PatternStatus, { props: { pattern: pattern({ bars_ago: barsAgo }) } });
    expect(wrapper.text()).toContain(text);
  });

  it('renders compression as an ongoing neutral wait', () => {
    const wrapper = mount(PatternStatus, {
      props: {
        pattern: pattern({
          pattern_type: 'compression_expansion',
          pattern_name: '波动压缩',
          direction: 'neutral_wait',
          stage: 'forming',
          confirmed: false,
        }),
      },
    });
    expect(wrapper.text()).toContain('等待方向');
    expect(wrapper.text()).toContain('波动压缩 · 持续中');
    expect(wrapper.get('span.flex').classes()).toContain('text-amber-500');
  });

  it('shows quality, reasons, levels, times, trading date and session in tooltip', async () => {
    const wrapper = mount(PatternStatus, { attachTo: document.body, props: { pattern: pattern() } });
    await wrapper.get('[tabindex="0"]').trigger('focus');
    const content = document.body.querySelector('[role="tooltip"]')?.textContent ?? '';
    expect(content).toContain('形态质量分：84 / 100');
    expect(content).toContain('突破前高后快速收回');
    expect(content).toContain('参考价位：132.50');
    expect(content).toContain('失效价位：132.70');
    expect(content).toContain('形态开始时间：');
    expect(content).toContain('确认时间：');
    expect(content).toContain('K线数量差：2 根');
    expect(content).toContain('交易日：2026-07-22');
    expect(content).toContain('交易时段：Intraday');
    expect(content).not.toContain('胜率');
    expect(content).not.toContain('Call');
    expect(content).not.toContain('Put');
  });

  it.each([
    [undefined, '数据不足'],
    [{ timeframe: '1m', status: 'insufficient' } as RealtimePatternState, '数据不足'],
    [{ timeframe: '1m', status: 'none' } as RealtimePatternState, '暂无近期形态'],
  ])('handles missing and empty states', (value, text) => {
    const wrapper = mount(PatternStatus, { props: { pattern: value } });
    expect(wrapper.text()).toContain(text);
    expect(wrapper.get('span.flex').classes()).toContain('text-muted-text');
  });
});
