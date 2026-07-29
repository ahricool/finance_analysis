import type { RealtimePatternState } from '@/api/realtimeMarket';
import { mount } from '@vue/test-utils';
import { afterEach, describe, expect, it } from 'vitest';
import PatternStatus from '../PatternStatus.vue';

const NOW = new Date('2026-07-22T14:36:00Z');

function pattern(
  overrides: Partial<NonNullable<RealtimePatternState['signal']>> = {},
): RealtimePatternState {
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
      occurred_at: '2026-07-22T14:20:00Z',
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

function withPreview(
  formal: RealtimePatternState = pattern(),
  overrides: Partial<NonNullable<RealtimePatternState['preview_signal']>> = {},
): RealtimePatternState {
  const source = pattern().signal!;
  return {
    ...formal,
    preview_status: 'active',
    preview_bar_time: '2026-07-22T14:36:00Z',
    preview_price: 133.25,
    preview_updated_at: '2026-07-22T14:36:20Z',
    preview_signal: {
      ...source,
      stage: 'warning',
      confirmed: false,
      confirmed_at: null,
      reasons: [...source.reasons, '实时预览：当前一分钟K线尚未收盘，信号可能变化'],
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
    const wrapper = mount(PatternStatus, {
      props: { pattern: pattern({ direction, stage, confirmed: stage === 'confirmed' }), now: NOW },
    });
    expect(wrapper.text()).toContain(text);
    expect(wrapper.get('span.font-semibold').classes()).toContain(color);
  });

  it('displays the backend quality score directly without recalculation', () => {
    const wrapper = mount(PatternStatus, {
      props: { pattern: pattern({ quality_score: 80, direction: 'neutral_wait' }), now: NOW },
    });
    expect(wrapper.text()).toContain('80分');
  });

  it('uses confirmed_at for a confirmed signal', () => {
    const wrapper = mount(PatternStatus, { props: { pattern: pattern(), now: NOW } });
    expect(wrapper.text()).toContain('已确认 · 84分 · 3分钟前');
    expect(wrapper.text()).not.toContain('16分钟前');
  });

  it.each([
    ['warning', '观察'],
    ['forming', '形成中'],
  ] as const)('uses occurred_at for a %s signal', (stage, stageLabel) => {
    const wrapper = mount(PatternStatus, {
      props: {
        pattern: pattern({
          stage,
          confirmed: false,
          occurred_at: '2026-07-22T14:28:00Z',
          confirmed_at: '2026-07-22T14:35:00Z',
        }),
        now: NOW,
      },
    });
    expect(wrapper.text()).toContain(`${stageLabel} · 84分 · 8分钟前`);
  });

  it('does not turn bars_ago into wall-clock minutes after the market stops producing bars', () => {
    const wrapper = mount(PatternStatus, {
      props: { pattern: pattern({ bars_ago: 1 }), now: new Date('2026-07-22T22:36:00Z') },
    });
    expect(wrapper.text()).toContain('8小时前');
    expect(wrapper.text()).not.toContain('1分钟前');
  });

  it('updates the relative time when the shared current time advances', async () => {
    const wrapper = mount(PatternStatus, { props: { pattern: pattern(), now: NOW } });
    expect(wrapper.text()).toContain('3分钟前');
    await wrapper.setProps({ now: new Date('2026-07-22T14:37:00Z') });
    expect(wrapper.text()).toContain('4分钟前');
  });

  it('shows the invalidation line only when a valid price exists', () => {
    const withPrice = mount(PatternStatus, { props: { pattern: pattern(), now: NOW } });
    const withoutPrice = mount(PatternStatus, {
      props: { pattern: pattern({ invalidation_price: null }), now: NOW },
    });
    expect(withPrice.text()).toContain('失效：132.70');
    expect(withoutPrice.text()).not.toContain('失效：');
  });

  it('renders compression with a neutral directional title and real event age', () => {
    const wrapper = mount(PatternStatus, {
      props: {
        pattern: pattern({
          pattern_type: 'compression_expansion',
          pattern_name: '波动压缩',
          direction: 'neutral_wait',
          stage: 'forming',
          confirmed: false,
          occurred_at: '2026-07-22T14:35:30Z',
        }),
        now: NOW,
      },
    });
    expect(wrapper.text()).toContain('等待方向');
    expect(wrapper.text()).toContain('形成中 · 84分 · 刚刚');
  });

  it('keeps quality, reasons, levels, times, bar age, trading date and session in the tooltip', async () => {
    const wrapper = mount(PatternStatus, {
      attachTo: document.body,
      props: { pattern: pattern(), now: NOW },
    });
    await wrapper.get('[tabindex="0"]').trigger('focus');
    const content = document.body.querySelector('[role="tooltip"]')?.textContent ?? '';
    expect(content).toContain('形态名称：假突破前高回收');
    expect(content).toContain('方向含义：多头结构向空头切换');
    expect(content).toContain('形态质量分：84 / 100');
    expect(content).toContain('突破前高后快速收回');
    expect(content).toContain('跌破回收结构低点');
    expect(content).toContain('参考价位：132.50');
    expect(content).toContain('失效价位：132.70');
    expect(content).toContain('形态开始时间：');
    expect(content).toContain('确认时间：');
    expect(content).toContain('K线数量差：2 根');
    expect(content).toContain('交易时段分钟差：2 分钟');
    expect(content).toContain('交易日：2026-07-22');
    expect(content).toContain('交易时段：Intraday');
  });

  it('renders only a live preview when no formal signal exists', () => {
    const wrapper = mount(PatternStatus, {
      props: {
        pattern: withPreview({ timeframe: '1m', status: 'none', signal: null }),
        now: NOW,
      },
    });
    expect(wrapper.text()).toContain('实时预览');
    expect(wrapper.text()).toContain('未收盘');
    expect(wrapper.text()).not.toContain('暂无近期形态');
    expect(wrapper.find('.text-red-500').exists()).toBe(false);
    expect(wrapper.find('.text-amber-500').exists()).toBe(true);
  });

  it('renders formal and preview signals separately even when they match', () => {
    const wrapper = mount(PatternStatus, { props: { pattern: withPreview(), now: NOW } });
    expect(wrapper.text()).toContain('正式 · 多转空确认');
    expect(wrapper.text()).toContain('实时预览 · 多转空预警 · 未收盘');
  });

  it('shows preview price, bar time, update time and warning in the tooltip', async () => {
    const wrapper = mount(PatternStatus, {
      attachTo: document.body,
      props: { pattern: withPreview(), now: NOW },
    });
    await wrapper.get('[tabindex="0"]').trigger('focus');
    const content = document.body.querySelector('[role="tooltip"]')?.textContent ?? '';
    expect(content).toContain('【正式形态】');
    expect(content).toContain('【实时预览 · 当前一分钟K线未收盘】');
    expect(content).toContain('当前预览价格：133.25');
    expect(content).toContain('当前K线时间：');
    expect(content).toContain('预览更新时间：');
    expect(content).toContain('一分钟K线尚未收盘，信号可能变化，不作为正式确认信号');
  });

  it('accepts old API data without preview fields', () => {
    const wrapper = mount(PatternStatus, { props: { pattern: pattern(), now: NOW } });
    expect(wrapper.text()).toContain('正式 · 多转空确认');
    expect(wrapper.text()).not.toContain('实时预览');
  });

  it.each([
    [undefined, '数据不足'],
    [{ timeframe: '1m', status: 'insufficient' } as RealtimePatternState, '数据不足'],
    [{ timeframe: '1m', status: 'none' } as RealtimePatternState, '暂无近期形态'],
  ])('handles missing and empty states', (value, text) => {
    const wrapper = mount(PatternStatus, { props: { pattern: value, now: NOW } });
    expect(wrapper.text()).toContain(text);
    expect(wrapper.get('span.font-semibold').classes()).toContain('text-muted-foreground');
  });
});
