import { onScopeDispose } from 'vue';

/**
 * Interval polling that stops while the tab is hidden. On return it refreshes at
 * once only if a full interval elapsed, so quick tab switches cost no requests.
 * The caller does the initial load; this only schedules follow-up refreshes.
 */
export function useVisiblePolling(callback: () => void, intervalMs: number) {
  let timer: number | null = null;
  let lastRun = Date.now();
  function run() { lastRun = Date.now(); callback(); }
  function start() {
    if (timer === null) timer = window.setInterval(run, intervalMs);
  }
  function stop() {
    if (timer !== null) window.clearInterval(timer);
    timer = null;
  }
  function onVisibility() {
    if (document.visibilityState === 'hidden') { stop(); return; }
    if (Date.now() - lastRun >= intervalMs) run();
    start();
  }
  if (document.visibilityState !== 'hidden') start();
  document.addEventListener('visibilitychange', onVisibility);
  onScopeDispose(() => {
    stop();
    document.removeEventListener('visibilitychange', onVisibility);
  });
  return { stop };
}
