import type { DailyBar } from '@/api/marketData';
import { isValidDailyBar, type DailyPatternDirection, type DailyPatternOptions } from './dailyPatterns';

export type DailyStructureType = 'box' | 'double_bottom' | 'double_top' | 'ascending_triangle' |
  'descending_triangle' | 'symmetric_triangle' | 'breakout_retest' | 'breakdown_retest';
export type StructureStatus = 'forming' | 'confirmed' | 'invalidated';
export interface StructureLine { name: string; startDate: string; startValue: number; endDate: string; endValue: number }
export interface DailyStructureEvent {
  id: string;
  structureId: string;
  date: string;
  timestamp: number;
  startDate: string;
  type: DailyStructureType;
  name: string;
  direction: DailyPatternDirection;
  status: StructureStatus;
  barConfirmed: boolean;
  quality: number;
  reasons: string[];
  lines: StructureLine[];
}
export const STRUCTURE_NAMES: Record<DailyStructureType, string> = {
  box: '箱体', double_bottom: '双底', double_top: '双顶', ascending_triangle: '上升三角形',
  descending_triangle: '下降三角形', symmetric_triangle: '对称三角形',
  breakout_retest: '突破后回踩', breakdown_retest: '跌破后反抽',
};
export function structureStatusLabel(event: DailyStructureEvent): string {
  if (!event.barConfirmed) {
    if (event.status === 'invalidated') return '失效待收盘';
    if (event.status === 'forming') return '当日预演';
    return event.type.endsWith('_retest') ? '回测待收盘' : '突破待收盘';
  }
  return ({ forming: '形成中', confirmed: '结构确认', invalidated: '失效' })[event.status];
}
interface Pivot { index: number; value: number }
interface Boundary { origin: number; value: number; slope: number }
interface Shape {
  id: string;
  type: Exclude<DailyStructureType, 'breakout_retest' | 'breakdown_retest'>;
  start: number;
  discovered: number;
  upper: Boundary;
  lower: Boundary;
  direction: DailyPatternDirection;
  quality: number;
  reasons: string[];
  tolerance: number;
  status: StructureStatus;
  brokenAt?: number;
  brokenLevel?: number;
  retested?: boolean;
  done?: boolean;
}
const at = (line: Boundary, index: number) => line.value + line.slope * (index - line.origin);
const flat = (index: number, value: number): Boundary => ({ origin: index, value, slope: 0 });
function fit(points: Pivot[]): Boundary {
  const origin = points[0]!.index;
  const xs = points.map(point => point.index - origin);
  const x = xs.reduce((sum, value) => sum + value, 0) / xs.length;
  const y = points.reduce((sum, point) => sum + point.value, 0) / points.length;
  const slope = points.reduce((sum, point, i) => sum + (xs[i]! - x) * (point.value - y), 0) /
    xs.reduce((sum, value) => sum + (value - x) ** 2, 0);
  return { origin, value: y - slope * x, slope };
}
function pivots(bars: readonly DailyBar[], start: number, end: number, high: boolean): Pivot[] {
  const result: Pivot[] = [];
  // A pivot becomes available only after its two right-hand candles. Never backdate the event.
  for (let i = start + 2; i <= end - 2; i++) {
    const value = high ? bars[i]!.high : bars[i]!.low;
    const adjacent = [i - 2, i - 1, i + 1, i + 2].map(j => high ? bars[j]!.high : bars[j]!.low);
    if (adjacent.every(other => high ? value > other : value < other)) result.push({ index: i, value });
  }
  return result;
}
function validWindow(bars: readonly DailyBar[], start: number, end: number) {
  for (let i = start; i <= end; i++) {
    if (!isValidDailyBar(bars[i]!) || (i > start && bars[i]!.tradeDate <= bars[i - 1]!.tradeDate)) return false;
  }
  return true;
}
function discover(bars: readonly DailyBar[], end: number): Shape[] {
  const result: Shape[] = [];
  const add = (shape: Omit<Shape, 'discovered' | 'status'>) => result.push({ ...shape, discovered: end + 1, status: 'forming' });
  for (const length of [60, 40, 20]) {
    const start = end - length + 1;
    if (start < 0 || !validWindow(bars, start, end)) continue;
    const sample = bars.slice(start, end + 1);
    const price = bars[end]!.close;
    const tolerance = Math.max(price * 0.005,
      sample.reduce((sum, bar) => sum + bar.high - bar.low, 0) / length * 0.5);
    const highs = pivots(bars, start, end, true);
    const lows = pivots(bars, start, end, false);
    if (highs.length < 2 || lows.length < 2 || highs.at(-1)!.index - highs[0]!.index < length * 0.4 ||
      lows.at(-1)!.index - lows[0]!.index < length * 0.4) continue;
    const max = Math.max(...sample.map(bar => bar.high));
    const min = Math.min(...sample.map(bar => bar.low));
    const highTouches = highs.filter(point => max - point.value <= tolerance);
    const lowTouches = lows.filter(point => point.value - min <= tolerance);
    if ((max - min) / price >= 0.03 && (max - min) / price <= 0.25 &&
      highTouches.length >= 2 && lowTouches.length >= 2 &&
      highTouches.at(-1)!.index - highTouches[0]!.index >= 5 && lowTouches.at(-1)!.index - lowTouches[0]!.index >= 5) {
      add({ id: `box:${highTouches[0]!.index}:${lowTouches[0]!.index}`, type: 'box', start,
        upper: flat(start, max), lower: flat(start, min), direction: 'neutral', tolerance,
        quality: Math.min(90, 70 + 2 * (highTouches.length + lowTouches.length)),
        reasons: [`此前 ${length} 根日 K 内上下边界各至少两次触及，箱体宽度 ${((max - min) / price * 100).toFixed(1)}%`] });
    }
    const upper = fit(highs);
    const lower = fit(lows);
    const upperMove = upper.slope * (length - 1) / price;
    const lowerMove = lower.slope * (length - 1) / price;
    const widthStart = at(upper, start) - at(lower, start);
    const widthEnd = at(upper, end) - at(lower, end);
    if (widthStart / price < 0.04 || widthEnd <= price * 0.01 ||
      widthEnd / widthStart < 0.2 || widthEnd / widthStart > 0.8 ||
      !highs.every(point => Math.abs(point.value - at(upper, point.index)) <= tolerance) ||
      !lows.every(point => Math.abs(point.value - at(lower, point.index)) <= tolerance) ||
      !sample.every((bar, i) => bar.high <= at(upper, start + i) + tolerance &&
        bar.low >= at(lower, start + i) - tolerance)) continue;
    let type: Shape['type'] | undefined;
    let direction: DailyPatternDirection = 'neutral';
    if (Math.abs(upperMove) <= 0.015 && lowerMove >= 0.02) { type = 'ascending_triangle'; direction = 'bullish'; }
    else if (upperMove <= -0.02 && Math.abs(lowerMove) <= 0.015) { type = 'descending_triangle'; direction = 'bearish'; }
    else if (upperMove <= -0.02 && lowerMove >= 0.02) type = 'symmetric_triangle';
    if (type) add({ id: `${type}:${highs[0]!.index}:${lows[0]!.index}`, type, start, upper, lower, direction, tolerance,
      quality: Math.round(75 + 15 * (1 - widthEnd / widthStart)),
      reasons: [`此前 ${length} 根日 K 中，上下边界各由至少两个已确认拐点拟合`,
        `边界间距收敛 ${(100 * (1 - widthEnd / widthStart)).toFixed(0)}%，所有 K 线均在边界容差内`] });
  }
  const start = Math.max(0, end - 119);
  if (end - start + 1 < 40 || !validWindow(bars, start, end)) return result;
  for (const bullish of [true, false]) {
    const points = pivots(bars, start, end, !bullish).slice(-5);
    const sign = bullish ? 1 : -1;
    // Use the latest consecutive extrema; do not skip intervening troughs/peaks to manufacture a double.
    if (points.length >= 2) {
      const first = points.at(-2)!;
      const second = points.at(-1)!;
      if (second.index - first.index < 20 || second.index - first.index > 90 || first.index < 6 ||
        Math.abs(first.value - second.value) / first.value > 0.03) continue;
      const middle = bars.slice(first.index + 1, second.index);
      const neck = bullish ? Math.max(...middle.map(bar => bar.high)) : Math.min(...middle.map(bar => bar.low));
      const extreme = bullish ? Math.min(first.value, second.value) : Math.max(first.value, second.value);
      if (sign * (neck - extreme) / extreme < 0.04 ||
        middle.some(bar => bullish ? bar.low < extreme - extreme * 0.005 : bar.high > extreme + extreme * 0.005) ||
        sign * (bars[first.index - 6]!.close - first.value) / first.value < 0.03 ||
        !validWindow(bars, first.index - 6, end) ||
        bars.slice(second.index + 1, end + 1).some(bar => sign * (bar.close - neck) > neck * 0.005)) continue;
      const type = bullish ? 'double_bottom' : 'double_top';
      add({ id: `${type}:${first.index}:${second.index}`, type, start: first.index,
        upper: flat(first.index, bullish ? neck : extreme), lower: flat(first.index, bullish ? extreme : neck),
        direction: bullish ? 'bullish' : 'bearish', tolerance: neck * 0.005,
        quality: Math.round(80 + 10 * (1 - Math.abs(first.value - second.value) / first.value / 0.03)),
        reasons: [`两个${bullish ? '低' : '高'}点间隔 ${second.index - first.index} 根 K，价格偏差不超过3%`,
          `中间反弹／回落深度至少4%，前置趋势至少3%；颈线 ${neck.toFixed(2)}`] });
    }
  }
  return result;
}

/** Causal event timeline. Frozen boundaries are evaluated from discovery forward, never rewritten. */
export function detectDailyStructures(bars: readonly DailyBar[], options: DailyPatternOptions = {}): DailyStructureEvent[] {
  const events: DailyStructureEvent[] = [];
  const shapes: Shape[] = [];
  const seen = new Set<string>();
  const emit = (shape: Shape, end: number, status: StructureStatus, reason: string, retest = false) => {
    if (shape.quality < Math.max(70, options.minQuality ?? 70)) return;
    const bar = bars[end]!;
    const barConfirmed = !!options.marketDate && bar.tradeDate < options.marketDate;
    const type = retest ? (shape.direction === 'bullish' ? 'breakout_retest' : 'breakdown_retest') : shape.type;
    const name = shape.type === 'box' && status === 'confirmed' && !retest
      ? (shape.direction === 'bullish' ? '箱体向上突破' : '箱体向下跌破') : STRUCTURE_NAMES[type];
    const lines = [shape.upper, shape.lower].map((line, i) => ({
      name: shape.type.startsWith('double_') && ((shape.direction === 'bullish' && i === 0) ||
        (shape.direction === 'bearish' && i === 1)) ? '颈线' : i === 0 ? '阻力' : '支撑',
      startDate: bars[shape.start]!.tradeDate, startValue: at(line, shape.start),
      endDate: bar.tradeDate, endValue: at(line, end),
    }));
    if (shape.brokenLevel !== undefined) lines.push({ name: '原突破位', startDate: bars[shape.brokenAt!]!.tradeDate,
      startValue: shape.brokenLevel, endDate: bar.tradeDate, endValue: shape.brokenLevel });
    events.push({ id: `${shape.id}:${type}:${status}:${bar.tradeDate}`, structureId: shape.id, date: bar.tradeDate,
      timestamp: Date.parse(`${bar.tradeDate}T00:00:00Z`), startDate: bars[shape.start]!.tradeDate,
      type, name, direction: shape.direction, status, barConfirmed, quality: shape.quality, lines,
      reasons: [...shape.reasons, reason, `识别日 ${bar.tradeDate}；拐点须等右侧两根已完成日 K，标记不提前到拐点日`] });
  };
  for (let end = 20; end < bars.length; end++) {
    if (!validWindow(bars, end - 1, end)) {
      shapes.forEach(shape => { shape.done = true; });
      continue;
    }
    const bar = bars[end]!;
    const closed = !!options.marketDate && bar.tradeDate < options.marketDate;
    // Only completed history can establish pivots and frozen levels, including in an unknown market.
    if (options.marketDate && bars[end - 1]!.tradeDate < options.marketDate) {
      for (const candidate of discover(bars, end - 1)) {
        if (seen.has(candidate.id)) continue;
        const overlapping = shapes.some(shape => !shape.done && shape.type === candidate.type &&
          candidate.start <= shape.discovered && end - shape.discovered <= 120);
        if (overlapping) continue;
        seen.add(candidate.id);
        shapes.push(candidate);
      }
    }
    for (const shape of shapes) {
      if (shape.done || end - shape.discovered > 120) { shape.done = true; continue; }
      const upper = at(shape.upper, end);
      const lower = at(shape.lower, end);
      if (upper <= lower && shape.status === 'forming') {
        emit(shape, end, 'invalidated', '收敛边界已相交而未出现有效突破，原结构失效');
        if (closed) shape.done = true;
        continue;
      }
      const up = bar.close > upper + shape.tolerance;
      const down = bar.close < lower - shape.tolerance;
      if (shape.status === 'forming') {
        const wrongBreak = (shape.direction === 'bullish' && down) || (shape.direction === 'bearish' && up);
        if (up || down) {
          if (wrongBreak) {
            emit(shape, end, 'invalidated', '收盘越过结构反方向边界，原方向结构失效');
            if (closed) shape.done = true;
          } else {
            const originalDirection = shape.direction;
            shape.direction = up ? 'bullish' : 'bearish';
            emit(shape, end, 'confirmed', `收盘${up ? '突破阻力' : '跌破支撑'}，超过边界容差 ${shape.tolerance.toFixed(2)}`);
            if (closed) {
              shape.status = 'confirmed'; shape.brokenAt = end; shape.brokenLevel = up ? upper : lower;
            } else shape.direction = originalDirection;
          }
        } else if (end === shape.discovered) emit(shape, end, 'forming', '结构已经具备几何条件，尚未收盘突破关键边界');
      } else if (shape.brokenAt !== undefined && shape.brokenLevel !== undefined) {
        const sign = shape.direction === 'bullish' ? 1 : -1;
        const failed = sign * (bar.close - shape.brokenLevel) < -shape.tolerance;
        if (failed) {
          emit(shape, end, 'invalidated', '收盘回到突破位内侧并超过容差，突破失效');
          if (closed) shape.done = true;
        } else if (!shape.retested && end - shape.brokenAt >= 3 && end - shape.brokenAt <= 15) {
          const touched = shape.direction === 'bullish' ? bar.low <= shape.brokenLevel + shape.tolerance :
            bar.high >= shape.brokenLevel - shape.tolerance;
          if (touched && sign * (bar.close - shape.brokenLevel) >= 0) {
            emit(shape, end, 'confirmed', `突破后第 ${end - shape.brokenAt} 根 K 触及原突破位 ${shape.brokenLevel.toFixed(2)} 并收在突破方向`, true);
            if (closed) shape.retested = true;
          }
        }
      }
    }
  }
  return events;
}

/** Latest transition per frozen structure prevents showing a stale confirmation after invalidation. */
export function recentDailyStructures(events: readonly DailyStructureEvent[], cutoff: string): DailyStructureEvent[] {
  const latest = new Map<string, DailyStructureEvent>();
  for (const event of events) latest.set(event.structureId, event);
  return [...latest.values()].filter(event => event.date >= cutoff)
    .sort((a, b) => b.date.localeCompare(a.date) || b.quality - a.quality || a.id.localeCompare(b.id)).slice(0, 3);
}
