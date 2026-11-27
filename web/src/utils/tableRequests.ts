// All inline charts share a bounded queue. Scrolling away removes queued work immediately.
const pending = new Set<() => void>();
let running = 0;
const limit = 4;

export function queueTableRequest<T>(signal: AbortSignal, read: () => Promise<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    function cancel() {
      pending.delete(start);
      reject(new DOMException('Request aborted', 'AbortError'));
    }
    function start() {
      pending.delete(start);
      signal.removeEventListener('abort', cancel);
      running++;
      void Promise.resolve().then(() => { signal.throwIfAborted(); return read(); }).then(resolve, reject).finally(() => {
        running--;
        pending.values().next().value?.();
      });
    }
    if (signal.aborted) cancel();
    else if (running < limit) start();
    else {
      pending.add(start);
      signal.addEventListener('abort', cancel, { once: true });
    }
  });
}
