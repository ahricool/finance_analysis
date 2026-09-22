/** Retry transient external HTTP failures; abort also cancels a pending backoff. */
export async function fetchExternal(url: string, signal: AbortSignal): Promise<Response> {
  const delays = [2000, 4000, 8000];
  for (let attempt = 0; ; attempt++) {
    signal.throwIfAborted();
    try {
      const response = await fetch(url, { signal, credentials: 'omit' });
      const transient = response.status === 408 || response.status === 429 || (response.status >= 500 && response.status < 600);
      if (!transient || attempt === delays.length) return response;
      await response.body?.cancel();
    } catch (error) {
      if (signal.aborted || !(error instanceof TypeError) || attempt === delays.length) throw error;
    }
    await new Promise<void>((resolve, reject) => {
      const cancel = () => {
        clearTimeout(timer);
        signal.removeEventListener('abort', cancel);
        reject(signal.reason);
      };
      const timer = setTimeout(() => {
        signal.removeEventListener('abort', cancel);
        resolve();
      }, delays[attempt]);
      signal.addEventListener('abort', cancel, { once: true });
      if (signal.aborted) cancel();
    });
  }
}
