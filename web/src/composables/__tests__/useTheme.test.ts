import { nextTick } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  initThemeRuntime,
  resolvedTheme,
  systemPrefersDark,
  theme,
  useTheme,
} from '@/composables/useTheme';

type MediaQueryListener = (event: MediaQueryListEvent) => void;

function mockMatchMedia(matches: boolean) {
  const listeners = new Set<MediaQueryListener>();
  const mql = {
    matches,
    media: '(prefers-color-scheme: dark)',
    onchange: null as MediaQueryListener | null,
    addEventListener: (_event: string, listener: MediaQueryListener) => {
      listeners.add(listener);
    },
    removeEventListener: (_event: string, listener: MediaQueryListener) => {
      listeners.delete(listener);
    },
    addListener: (listener: MediaQueryListener) => {
      listeners.add(listener);
    },
    removeListener: (listener: MediaQueryListener) => {
      listeners.delete(listener);
    },
    dispatchEvent: () => true,
    change(next: boolean) {
      this.matches = next;
      listeners.forEach((listener) => listener({ matches: next } as MediaQueryListEvent));
    },
  };
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: vi.fn(() => mql),
  });
  return mql;
}

describe('useTheme', () => {
  afterEach(() => {
    localStorage.removeItem('theme');
    theme.value = 'system';
    systemPrefersDark.value = false;
    document.documentElement.classList.remove('light', 'dark');
    document.documentElement.style.colorScheme = '';
  });

  it('defaults to system when storage is missing or invalid and does not overwrite existing values', () => {
    const { setTheme } = useTheme();

    localStorage.removeItem('theme');
    initThemeRuntime();
    expect(theme.value).toBe('system');
    expect(localStorage.getItem('theme')).toBeNull();

    localStorage.setItem('theme', 'not-a-theme');
    initThemeRuntime();
    expect(theme.value).toBe('system');
    expect(localStorage.getItem('theme')).toBe('not-a-theme');

    localStorage.setItem('theme', 'dark');
    initThemeRuntime();
    expect(theme.value).toBe('dark');
    expect(resolvedTheme.value).toBe('dark');

    localStorage.setItem('theme', 'light');
    initThemeRuntime();
    expect(theme.value).toBe('light');
    expect(resolvedTheme.value).toBe('light');

    setTheme('system');
    expect(localStorage.getItem('theme')).toBe('system');
  });

  it('resolves system preference and follows OS changes without a page reload', async () => {
    const mql = mockMatchMedia(false);
    const { setTheme } = useTheme();

    localStorage.removeItem('theme');
    initThemeRuntime();
    setTheme('system');

    expect(theme.value).toBe('system');
    expect(resolvedTheme.value).toBe('light');
    expect(document.documentElement.classList.contains('light')).toBe(true);
    expect(document.documentElement.classList.contains('dark')).toBe(false);

    mql.change(true);
    await nextTick();
    expect(systemPrefersDark.value).toBe(true);
    expect(theme.value).toBe('system');
    expect(resolvedTheme.value).toBe('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe('dark');

    setTheme('light');
    mql.change(true);
    await nextTick();
    expect(theme.value).toBe('light');
    expect(resolvedTheme.value).toBe('light');
    expect(document.documentElement.classList.contains('light')).toBe(true);

    setTheme('dark');
    mql.change(false);
    await nextTick();
    expect(theme.value).toBe('dark');
    expect(resolvedTheme.value).toBe('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });
});
