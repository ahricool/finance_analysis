import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { authApi } from '@/api/auth';
import { useAuthStore } from '../authStore';

vi.mock('@/api/auth', () => ({ authApi: { getStatus: vi.fn(), login: vi.fn(), logout: vi.fn() } }));
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => { setActivePinia(createPinia()); vi.resetAllMocks(); });
describe('session status request sharing', () => {
  it('shares the initial route/App request and clears it after completion', async () => {
    const request = deferred<{ loggedIn: boolean; user: null }>();
    vi.mocked(authApi.getStatus).mockReturnValueOnce(request.promise);
    const auth = useAuthStore();
    const route = auth.fetchStatus();
    const app = auth.fetchStatus();
    expect(authApi.getStatus).toHaveBeenCalledTimes(1);
    request.resolve({ loggedIn: true, user: null });
    await Promise.all([route, app]);
    expect(auth.loggedIn).toBe(true);
    expect(auth.isLoading).toBe(false);
    vi.mocked(authApi.getStatus).mockResolvedValueOnce({ loggedIn: false, user: null });
    await auth.fetchStatus();
    expect(authApi.getStatus).toHaveBeenCalledTimes(2);
    expect(auth.loggedIn).toBe(false);
  });
  it('ignores a stale status response when logout starts a fresh status request', async () => {
    const old = deferred<{ loggedIn: boolean; user: null }>();
    vi.mocked(authApi.getStatus).mockReturnValueOnce(old.promise).mockResolvedValueOnce({ loggedIn: false, user: null });
    const auth = useAuthStore();
    const pending = auth.fetchStatus();
    await auth.logout();
    old.resolve({ loggedIn: true, user: null });
    await pending;
    expect(auth.loggedIn).toBe(false);
    expect(auth.isLoading).toBe(false);
  });
  it('allows retry after a failed shared request', async () => {
    vi.mocked(authApi.getStatus).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ loggedIn: true, user: null });
    const auth = useAuthStore();
    await auth.fetchStatus();
    expect(auth.loadError).toBeTruthy();
    await auth.refreshStatus();
    expect(auth.loadError).toBeNull();
    expect(auth.loggedIn).toBe(true);
  });
});
