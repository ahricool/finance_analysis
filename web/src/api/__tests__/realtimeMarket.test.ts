import { afterEach, describe, expect, it, vi } from 'vitest';
import { MarketStreamAuthError, parseRealtimeQuoteMessage, readMarketEvents } from '../realtimeMarket';

const encoder = new TextEncoder();
afterEach(() => vi.unstubAllGlobals());

describe('realtime quote wire mapping', () => {
  it('maps snake_case quotes to camelCase with explicit 1m keys', () => {
    const message = parseRealtimeQuoteMessage({
      type: 'quotes', generated_at: 'now',
      quotes: [{
        code: '600519.SH', market_type: 'CN', symbol: '600519.SH', available: true, last_price: 10, pre_close: 9,
        trend_1m: { timeframe: '1m', target_period: 20, effective_period: 8, minimum_period: 5, state: 'above', streak: 1, confirmed: true },
        pattern_1m: { timeframe: '1m', status: 'active', preview_status: 'none',
          signal: { pattern_name: '回踩', quality_score: 80, bars_ago: 1, reasons: ['vwap_reclaim'] } },
      }],
    });
    expect(message?.generatedAt).toBe('now');
    expect(message?.portfolio).toBeNull();
    expect(message?.quotes[0]).toMatchObject({
      marketType: 'CN', lastPrice: 10, preClose: 9,
      trend1m: { targetPeriod: 20, effectivePeriod: 8, minimumPeriod: 5 },
      pattern1m: { previewStatus: 'none', signal: { patternName: '回踩', qualityScore: 80, barsAgo: 1, reasons: ['vwap_reclaim'] } },
    });
    expect(message?.quotes[0]).not.toHaveProperty('trend1M');
  });

  it('rejects non-quote frames', () => {
    expect(parseRealtimeQuoteMessage({ type: 'error' })).toBeNull();
    expect(parseRealtimeQuoteMessage(null)).toBeNull();
  });
});

describe('HTTP market events', () => {
  it('decodes fragmented UTF8 and CRLF frames with cookies and portfolio fields', async () => {
    const controller = new AbortController();
    const message = { type: 'quotes', generated_at: 'now', quotes: [], portfolio: { accounts: [], positions: [], market: 'CN', name: '股票' } };
    const bytes = encoder.encode(`: heartbeat\r\n\r\ndata: broken\n\ndata: ${JSON.stringify(message)}\r\n\r\n`);
    const fetcher = vi.fn().mockResolvedValue(new Response(new ReadableStream({
      start(stream) {
        for (let i = 0; i < bytes.length; i += 3) stream.enqueue(bytes.slice(i, i + 3));
        stream.close();
      },
    })));
    vi.stubGlobal('fetch', fetcher);
    const received: unknown[] = [];
    await readMarketEvents({ scope: 'holdings', market: 'CN' }, controller.signal, value => {
      received.push(value); controller.abort();
    });
    expect(received).toEqual([{
      type: 'quotes', generatedAt: 'now', quotes: [],
      portfolio: { accounts: [], positions: [], market: 'CN', name: '股票' },
    }]);
    expect(String(fetcher.mock.calls[0]![0])).toContain('/api/v1/market-data/events?scope=holdings&market=CN');
    expect(fetcher.mock.calls[0]![1]).toMatchObject({ credentials: 'include', signal: controller.signal });
  });

  it('distinguishes authorization failures from retriable stream errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })));
    await expect(readMarketEvents({}, new AbortController().signal, () => {})).rejects.toBeInstanceOf(MarketStreamAuthError);
  });

  it('reports headers, heartbeat, error and fragmented bytes as activity without treating them as quotes', async () => {
    const controller = new AbortController();
    let stream!: ReadableStreamDefaultController<Uint8Array>;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new ReadableStream<Uint8Array>({
      start(value) { stream = value; },
    }))));
    const onMessage = vi.fn();
    const onActivity = vi.fn();
    const reading = readMarketEvents({}, controller.signal, onMessage, onActivity);
    await vi.waitFor(() => expect(onActivity).toHaveBeenCalledTimes(1));
    for (const [index, frame] of [': heartbeat\n\n', 'data: {"type":"error"}\n\n', 'data: {'].entries()) {
      stream.enqueue(encoder.encode(frame));
      await vi.waitFor(() => expect(onActivity).toHaveBeenCalledTimes(index + 2));
    }
    expect(onMessage).not.toHaveBeenCalled();
    controller.abort();
    stream.close();
    await expect(reading).rejects.toThrow('行情连接已断开');
  });
});
