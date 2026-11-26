import { describe, expect, it, vi } from 'vitest';
import type { IntradayBar, TradeSession } from '@/api/intradayMarket';
import { tradingSessionOverlays } from '../tradingSessionOverlay';

vi.mock('klinecharts', () => ({ registerOverlay: vi.fn() }));
const bar = (minute: number, tradeSession: TradeSession): IntradayBar => ({
  timestamp: minute * 60_000, open: 10, high: 11, low: 9, close: 10, volume: 1, turnover: 10,
  confirmed: true, sampled: false, sampleCount: 0, partial: false, tradeSession,
});

describe('US minute session bands', () => {
  it('groups native minute labels in order, including overnight across midnight and single-minute segments', () => {
    const overlays = tradingSessionOverlays([bar(0, 'post'), bar(1, 'overnight'), bar(2, 'overnight'),
      bar(3, 'pre'), bar(4, 'regular'), bar(5, 'regular'), bar(6, 'post')]);
    expect(overlays.map(o => (o.extendData as { session: TradeSession }).session)).toEqual(['post', 'overnight', 'pre', 'regular', 'post']);
    expect(overlays[1]?.points?.map(p => p.timestamp)).toEqual([60_000, 120_000]);
    expect(overlays[2]?.points?.map(p => p.timestamp)).toEqual([180_000, 180_000]);
  });
});
