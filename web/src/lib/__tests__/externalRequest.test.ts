import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchExternal } from '../externalRequest';

describe('external request retries', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it('retries a transient response after 2, 4, and 8 seconds then stops', async () => {
    const fetch = vi.fn().mockImplementation(async () => new Response('', { status: 503 }));
    vi.stubGlobal('fetch', fetch);
    const result = fetchExternal('https://example.test', new AbortController().signal);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetch).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(4000);
    expect(fetch).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(8000);
    expect(fetch).toHaveBeenCalledTimes(4);
    expect((await result).status).toBe(503);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('recovers after a network failure and does not retry authentication errors', async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new TypeError('network'))
      .mockResolvedValueOnce(new Response('', { status: 200 }))
      .mockResolvedValueOnce(new Response('', { status: 401 }));
    vi.stubGlobal('fetch', fetch);
    const result = fetchExternal('https://example.test', new AbortController().signal);
    await vi.advanceTimersByTimeAsync(2000);
    expect((await result).status).toBe(200);
    expect((await fetchExternal('https://example.test', new AbortController().signal)).status).toBe(401);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('cancels pending backoff when the user switches interval or leaves', async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError('network'));
    vi.stubGlobal('fetch', fetch);
    const controller = new AbortController();
    const result = fetchExternal('https://example.test', controller.signal);
    const assertion = expect(result).rejects.toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();
    await assertion;
    await vi.advanceTimersByTimeAsync(14000);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});
