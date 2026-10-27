import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { effectScope } from 'vue';
import { useVisiblePolling } from '../useVisiblePolling';

let visibility: DocumentVisibilityState = 'visible';
function setVisibility(value: DocumentVisibilityState) {
  visibility = value;
  document.dispatchEvent(new Event('visibilitychange'));
}

beforeEach(() => {
  visibility = 'visible';
  vi.useFakeTimers();
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('visible polling', () => {
  it('polls only while visible and catches up after a long absence', () => {
    const callback = vi.fn();
    const scope = effectScope();
    scope.run(() => useVisiblePolling(callback, 1_000));
    vi.advanceTimersByTime(2_000);
    expect(callback).toHaveBeenCalledTimes(2);
    setVisibility('hidden');
    vi.advanceTimersByTime(5_000);
    expect(callback).toHaveBeenCalledTimes(2);
    setVisibility('visible');
    expect(callback).toHaveBeenCalledTimes(3);
    vi.advanceTimersByTime(1_000);
    expect(callback).toHaveBeenCalledTimes(4);
    scope.stop();
    vi.advanceTimersByTime(5_000);
    expect(callback).toHaveBeenCalledTimes(4);
  });

  it('skips the catch-up refresh after a brief hide', () => {
    const callback = vi.fn();
    const scope = effectScope();
    scope.run(() => useVisiblePolling(callback, 1_000));
    vi.advanceTimersByTime(300);
    setVisibility('hidden');
    vi.advanceTimersByTime(200);
    setVisibility('visible');
    expect(callback).not.toHaveBeenCalled();
    scope.stop();
  });
});
