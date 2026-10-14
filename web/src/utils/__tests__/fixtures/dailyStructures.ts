import { candle, dated, mirror } from './dailyPatterns';

export function box() {
  return dated(Array.from({ length: 60 }, (_, i) => {
    const price = 100 + 5 * Math.cos((i - 3) * Math.PI / 6);
    return candle(price - 0.1, price, price - 0.3, price + 0.3);
  }));
}
export function triangle(kind: 'ascending' | 'descending' | 'symmetric' = 'ascending') {
  const bars = dated(Array.from({ length: 60 }, (_, i) => {
    const upper = kind === 'symmetric' ? 115 - i * 0.15 : 110;
    const lower = kind === 'symmetric' ? 85 + i * 0.15 : 90 + i * 0.15;
    const wave = (1 + Math.cos(i * Math.PI / 6)) / 2;
    const price = lower + (upper - lower) * wave;
    return candle(price - 0.1, price, price - 0.25, price + 0.25);
  }));
  return kind === 'descending' ? mirror(bars) : bars;
}
export function doubleBottom() {
  const knots = [[0, 115], [12, 90], [25, 105], [40, 90.5], [44, 100]] as const;
  return dated(Array.from({ length: 45 }, (_, i) => {
    const right = knots.findIndex(point => point[0] >= i);
    const a = knots[Math.max(0, right - 1)]!;
    const b = knots[right]!;
    const price = a[0] === b[0] ? a[1] : a[1] + (b[1] - a[1]) * (i - a[0]) / (b[0] - a[0]);
    return candle(price - 0.1, price, price - 0.3, price + 0.3);
  }));
}
