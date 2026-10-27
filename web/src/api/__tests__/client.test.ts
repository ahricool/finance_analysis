import { afterEach, describe, expect, it, vi } from 'vitest';

const assign = vi.fn();

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
  assign.mockReset();
});

async function loadClient(pathname: string) {
  vi.stubGlobal('location', { ...window.location, pathname, search: '?market=US', assign });
  return import('../index');
}

describe('apiClient 401 handling', () => {
  it('redirects to login once when several requests expire together', async () => {
    const { default: apiClient } = await loadClient('/research/quant');
    apiClient.defaults.adapter = async config => Promise.reject(Object.assign(new Error('Unauthorized'), {
      isAxiosError: true, config, response: { status: 401, data: {}, headers: {}, config, statusText: 'Unauthorized' },
    }));
    await Promise.allSettled([apiClient.get('/a'), apiClient.get('/b'), apiClient.get('/c')]);
    expect(assign.mock.calls).toEqual([['/login?redirect=%2Fresearch%2Fquant%3Fmarket%3DUS']]);
  });

  it('does not redirect while already on the login page', async () => {
    const { redirectToLogin } = await loadClient('/login');
    redirectToLogin();
    expect(assign).not.toHaveBeenCalled();
  });
});
