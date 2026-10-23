import { describe, expect, it, vi } from 'vitest';
import type { OverlayCreateFiguresCallback, OverlayCreateFiguresCallbackParams, OverlayFigure } from 'klinecharts';
import type { IntradayBar, PatternEvent } from '@/api/intradayMarket';
import type { PatternDirection } from '@/api/realtimeMarket';
import { intradayPatternOverlays } from '../intradayPatternOverlay';

const register = vi.hoisted(() => vi.fn());
vi.mock('klinecharts', () => ({ registerOverlay: register }));
const at = Date.parse('2026-10-21T15:00:00Z');
const bar: IntradayBar = { timestamp: at, open: 100, high: 102, low: 98, close: 101,
  volume: 10, turnover: null, confirmed: true, sampled: false, sample_count: 0, partial: false };
function event(direction: PatternDirection, seconds = 10): PatternEvent {
  return { timeframe: '1m', pattern_type: 'breakout_retest_continuation', pattern_name: '突破回踩延续',
    direction, stage: 'confirmed', quality_score: 83, occurred_at: new Date(at - 600_000).toISOString(),
    observed_at: new Date(at + seconds * 1000).toISOString(), bars_ago: 0, session_minutes_ago: 0,
    reference_level: 100, invalidation_price: 98, reasons: ['保存的原始证据'], confirmed: true };
}

describe('compact intraday pattern markers', () => {
  it('renders all seven directions as three small symbols with theme colors and bounded positions', () => {
    intradayPatternOverlays([], [], false, vi.fn());
    const draw = register.mock.calls.find(([overlay]) => overlay.name === 'intradayPattern')![0].createPointFigures as OverlayCreateFiguresCallback<{ event: PatternEvent; dark: boolean }>;
    const cases: Array<[PatternDirection, string, string, number]> = [
      ['bullish_continuation', '▴', '#dc2626', bar.low], ['bullish_breakout', '▴', '#dc2626', bar.low],
      ['bearish_to_bullish', '▴', '#dc2626', bar.low], ['bearish_continuation', '▾', '#16854e', bar.high],
      ['bearish_breakout', '▾', '#16854e', bar.high], ['bullish_to_bearish', '▾', '#16854e', bar.high],
      ['neutral_wait', '◇', '#888888', bar.high],
    ];
    for (const [direction, symbol, color, value] of cases) {
      const observation = event(direction);
      const overlay = intradayPatternOverlays([observation], [bar], false, vi.fn())[0]!;
      expect(overlay).toMatchObject({ name: 'intradayPattern', groupId: 'intraday-patterns',
        points: [{ timestamp: at, value }] });
      const params = { coordinates: [{ x: 100, y: value === bar.low ? 299 : 0 }],
        overlay, bounding: { height: 300 } } as unknown as OverlayCreateFiguresCallbackParams<{ event: PatternEvent; dark: boolean }>;
      const figures = draw(params) as OverlayFigure[];
      expect(figures).toHaveLength(1);
      expect(figures[0]).toMatchObject({ attrs: { text: symbol, y: value === bar.low ? 270 : 10 },
        styles: { color, weight: 'bold', backgroundColor: 'transparent' } });
      expect(JSON.stringify(figures)).not.toContain(observation.pattern_name);
    }
    const preview = { ...event('bullish_breakout'), stage: 'forming' as const, confirmed: false };
    const overlay = intradayPatternOverlays([preview], [bar], true, vi.fn())[0]!;
    expect(draw({ coordinates: [{ x: 100, y: 100 }], overlay, bounding: { height: 300 } } as never)).toMatchObject([
      { attrs: { text: '▴' }, styles: { color: '#e86464', weight: 'normal' } },
    ]);
    const bearishOverlay = intradayPatternOverlays([event('bearish_breakout')], [bar], true, vi.fn())[0]!;
    expect(draw({ coordinates: [{ x: 100, y: 100 }], overlay: bearishOverlay, bounding: { height: 300 } } as never)).toMatchObject([
      { attrs: { text: '▾' }, styles: { color: '#39b77a' } },
    ]);
  });

  it('groups the same minute by latest observation while retaining every event and never backdates to a pivot', () => {
    const first = event('bullish_breakout');
    const latest = event('neutral_wait', 30);
    const next = event('bullish_to_bearish', 70);
    const onSelect = vi.fn();
    const overlays = intradayPatternOverlays([latest, next, first], [bar, { ...bar, timestamp: at + 60_000 }], false, onSelect);
    expect(overlays).toHaveLength(2);
    expect(overlays[0]).toMatchObject({ id: `intraday-pattern-${at}`, extendData: { event: latest } });
    overlays[0]!.onClick!({} as never);
    expect(onSelect).toHaveBeenCalledWith([latest, first]);
    expect(overlays[1]!.points![0]!.timestamp).toBe(at + 60_000);
    expect(intradayPatternOverlays([event('bullish_breakout', -1), event('bullish_breakout', 121),
      { ...first, observed_at: 'invalid' }], [bar], false, onSelect)).toEqual([]);
    expect(intradayPatternOverlays([first], [], false, onSelect)).toEqual([]);
  });
});
