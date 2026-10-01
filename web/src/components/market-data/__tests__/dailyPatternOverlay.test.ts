import { expect, it, vi } from 'vitest';
import type { OverlayCreateFiguresCallback, OverlayCreateFiguresCallbackParams, OverlayFigure } from 'klinecharts';
import { dailyPatternOverlays } from '../dailyPatternOverlay';
import { detectDailyPatterns, type DailyPatternEvent } from '@/utils/dailyPatterns';
import { engulfing, mirror } from '@/utils/__tests__/fixtures/dailyPatterns';
const register = vi.hoisted(() => vi.fn());
vi.mock('klinecharts', () => ({ registerOverlay: register }));
it('renders short directional labels, distinct Preview style, theme colors and keeps edge markers inside the pane', () => {
  const bars = engulfing();
  const event = detectDailyPatterns(bars, { marketDate: '2026-09-09' })[0]!;
  const onSelect = vi.fn();
  const overlays = dailyPatternOverlays([event], bars, false, onSelect);
  expect(overlays[0]).toMatchObject({ name: 'dailyPattern', groupId: 'daily-patterns',
    points: [{ timestamp: event.timestamp, value: bars.at(-1)!.low }] });
  overlays[0]!.onClick!({} as never);
  expect(onSelect).toHaveBeenCalledWith(event);
  const draw = register.mock.calls[0]![0].createPointFigures as OverlayCreateFiguresCallback<DailyPatternEvent & { dark: boolean }>;
  function figure(item: DailyPatternEvent, dark: boolean, y: number) {
    const params = { coordinates: [{ x: 100, y }], overlay: { extendData: { ...item, dark } },
      bounding: { height: 300 } } as OverlayCreateFiguresCallbackParams<DailyPatternEvent & { dark: boolean }>;
    return (draw(params) as OverlayFigure[])[0]!;
  }
  expect(figure(event, false, 295)).toMatchObject({ attrs: { text: '↑ 吞没', y: 290 }, styles: { color: '#dc2626', weight: 'bold' } });
  expect(figure({ ...event, confirmed: false }, true, 100)).toMatchObject({
    attrs: { text: '↑ 吞没 · 形成中', y: 122 }, styles: { color: '#e86464', weight: 'normal', backgroundColor: '#171717' },
  });
  const bearishBars = mirror(bars);
  const bearish = detectDailyPatterns(bearishBars, { marketDate: '2026-09-09' })[0]!;
  expect(figure(bearish, false, 20)).toMatchObject({ attrs: { text: '↓ 吞没', y: 10 }, styles: { color: '#16854e' } });
  expect(dailyPatternOverlays([bearish], bearishBars, true, onSelect)[0]!.points![0]!.value).toBe(bearishBars.at(-1)!.high);
  expect(dailyPatternOverlays([], bars, false, onSelect)).toEqual([]);
  expect(dailyPatternOverlays([event], [], false, onSelect)).toEqual([]);
});
