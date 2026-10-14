import { describe, expect, it } from 'vitest';
import { detectDailyPatterns } from '../dailyPatterns';
import { candle, dated, falling, hammer, mirror } from './fixtures/dailyPatterns';
const options = { marketDate: '2027-01-01' };
const piercing = () => dated([...falling(), candle(100, 94, 93.8, 100.2), candle(93.8, 99, 93.6, 99.2)]);
const harami = () => dated([...falling(), candle(100, 94, 93.8, 100.2), candle(96, 98, 95.8, 98.2)]);
const soldiers = () => dated([...falling(), candle(96, 98, 95.8, 98.2),
  candle(97, 99.5, 96.8, 99.7), candle(98, 101, 97.8, 101.2)]);
const inverted = () => dated([...falling(), candle(98, 99, 97.8, 103.5)]);
const hanging = () => dated([...mirror(falling()), ...hammer().slice(-1)]);

describe('additional candlestick observations', () => {
  it.each([
    ['piercing_line', piercing], ['dark_cloud_cover', () => mirror(piercing())],
    ['bullish_harami', harami], ['bearish_harami', () => mirror(harami())],
    ['three_white_soldiers', soldiers], ['three_black_crows', () => mirror(soldiers())],
    ['inverted_hammer', inverted], ['hanging_man', hanging],
  ] as const)('detects %s at the completion date', (type, fixture) => {
    const bars = fixture();
    const event = detectDailyPatterns(bars, options).find(event => event.date === bars.at(-1)!.tradeDate);
    expect(event?.type).toBe(type);
    expect(event?.quality).toBeGreaterThanOrEqual(70);
    expect(event?.confirmed).toBe(true);
  });
  it('treats a balanced doji as neutral, and filters tiny ranges and unbalanced shadows', () => {
    const bars = dated([...falling(), candle(99.99, 100, 98, 102)]);
    expect(detectDailyPatterns(bars, options).at(-1)).toMatchObject({ type: 'doji', direction: 'neutral' });
    for (const last of [candle(100, 100, 99.5, 100.5), candle(100, 100, 98, 100.2)]) {
      expect(detectDailyPatterns(dated([...falling(), last]), options).some(event => event.type === 'doji')).toBe(false);
    }
  });
  it('keeps trend context outside the entire 1/2/3 candle shape', () => {
    for (const fixture of [piercing, harami, soldiers, inverted]) {
      const bars = fixture();
      const flat = dated([...Array.from({ length: 6 }, () => candle(100, 100)), ...bars.slice(6)]);
      expect(detectDailyPatterns(flat, options)).toEqual([]);
    }
  });
  it('does not manufacture soldiers out of gaps or long direction-end shadows', () => {
    const bars = soldiers();
    bars.at(-1)!.open = 100;
    expect(detectDailyPatterns(bars, options).some(event => event.type === 'three_white_soldiers')).toBe(false);
    const shadow = soldiers(); shadow.at(-1)!.high = 103;
    expect(detectDailyPatterns(shadow, options).some(event => event.type === 'three_white_soldiers')).toBe(false);
  });
});
