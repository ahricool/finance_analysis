import { expect, it, vi } from 'vitest';
import type { OverlayCreateFiguresCallback, OverlayCreateFiguresCallbackParams, OverlayFigure } from 'klinecharts';
import { dailyStructureOverlays } from '../dailyStructureOverlay';
import { detectDailyStructures, type DailyStructureEvent } from '@/utils/dailyStructures';
import { box } from '@/utils/__tests__/fixtures/dailyStructures';
const register = vi.hoisted(() => vi.fn());
vi.mock('klinecharts', () => ({ registerOverlay: register }));
it('keeps names off canvas, shows boundaries only after selection, and supports hover and clicks', () => {
  const event = detectDailyStructures(box(), { marketDate: '2027-01-01' })[0]!;
  const select = vi.fn(); const hover = vi.fn();
  const overlay = dailyStructureOverlays([event], true, undefined, select, hover)[0]!;
  expect(overlay.groupId).toBe('daily-structures');
  expect(overlay.points).toHaveLength(1);
  overlay.onMouseEnter!({} as never); expect(hover).toHaveBeenLastCalledWith(event);
  overlay.onMouseLeave!({} as never); expect(hover).toHaveBeenLastCalledWith(null);
  overlay.onClick!({} as never); expect(select).toHaveBeenCalledWith(event);
  const selected = dailyStructureOverlays([event], true, event.id, select, hover)[0]!;
  expect(selected.points).toHaveLength(5);
  type Data = { event: DailyStructureEvent; dark: boolean; selected: boolean };
  const draw = register.mock.calls[0]![0].createPointFigures as OverlayCreateFiguresCallback<Data>;
  function figures(isSelected: boolean) {
    const params = { coordinates: [{ x: 100, y: 100 }, { x: 20, y: 50 }, { x: 100, y: 60 },
      { x: 20, y: 200 }, { x: 100, y: 190 }], bounding: { height: 300 },
      overlay: { extendData: { event, dark: true, selected: isSelected } } } as OverlayCreateFiguresCallbackParams<Data>;
    return draw(params) as OverlayFigure[];
  }
  expect(figures(false)).toHaveLength(1);
  expect(figures(false)[0]).toMatchObject({ type: 'text', attrs: { text: '◆', y: 288 }, styles: { size: 10 } });
  expect(figures(true).filter(figure => figure.type === 'line')).toHaveLength(2);
  expect(figures(true).filter(figure => figure.type === 'line').every(figure => figure.ignoreEvent)).toBe(true);
  const other = { ...event, id: 'other', quality: 99 };
  expect(dailyStructureOverlays([event, other], false, event.id, select, hover)[0]!.extendData).toMatchObject({ event: { id: event.id } });
  expect(dailyStructureOverlays([event, other], false, undefined, select, hover)).toHaveLength(1);
});
