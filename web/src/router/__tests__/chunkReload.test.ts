import { createMemoryHistory, createRouter } from 'vue-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installChunkReload, isChunkLoadError, reloadForStaleChunk } from '../chunkReload';

const assign = vi.fn();

beforeEach(() => {
  sessionStorage.clear();
  assign.mockReset();
  vi.stubGlobal('location', { ...window.location, assign });
});
afterEach(() => vi.unstubAllGlobals());

describe('stale chunk reload', () => {
  it.each([
    'Failed to fetch dynamically imported module: https://x/assets/Page-abc.js',
    'error loading dynamically imported module',
    'Importing a module script failed.',
    'Unable to preload CSS for /assets/Page-abc.css',
  ])('recognizes %s', message => {
    expect(isChunkLoadError(new TypeError(message))).toBe(true);
  });

  it('ignores ordinary errors', () => {
    expect(isChunkLoadError(new Error('Request failed with status code 500'))).toBe(false);
    expect(isChunkLoadError(null)).toBe(false);
  });

  it('reloads a URL once per cooldown window', () => {
    expect(reloadForStaleChunk('/research/quant', 1_000)).toBe(true);
    expect(reloadForStaleChunk('/research/quant', 5_000)).toBe(false);
    expect(reloadForStaleChunk('/dashboard', 5_000)).toBe(true);
    expect(reloadForStaleChunk('/research/quant', 20_000)).toBe(true);
    expect(assign.mock.calls).toEqual([['/research/quant'], ['/dashboard'], ['/research/quant']]);
  });

  it('reloads into the navigation target when a route chunk is gone', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/stale', component: () => Promise.reject(new TypeError('Failed to fetch dynamically imported module: /assets/Stale.js')) },
      ],
    });
    installChunkReload(router);
    await router.push('/');
    await router.push('/stale?market=US').catch(() => undefined);
    expect(assign).toHaveBeenCalledWith('/stale?market=US');
  });
});
