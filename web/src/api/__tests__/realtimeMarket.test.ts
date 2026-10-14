import { afterEach, describe, expect, it, vi } from 'vitest';
import { MarketStreamAuthError, readMarketEvents } from '../realtimeMarket';

const encoder = new TextEncoder();
afterEach(() => vi.unstubAllGlobals());

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
    expect(received).toEqual([message]);
    expect(String(fetcher.mock.calls[0]![0])).toContain('/api/v1/market-data/events?scope=holdings&market=CN');
    expect(fetcher.mock.calls[0]![1]).toMatchObject({ credentials: 'include', signal: controller.signal });
  });

  it('distinguishes authorization failures from retriable stream errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })));
    await expect(readMarketEvents({}, new AbortController().signal, () => {})).rejects.toBeInstanceOf(MarketStreamAuthError);
  });
});
