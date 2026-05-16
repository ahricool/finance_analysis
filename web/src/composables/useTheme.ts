import { computed, ref, watch } from 'vue';

export type ThemePreference = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'theme';

function readStored(): ThemePreference {
  if (typeof localStorage === 'undefined') return 'light';
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw === 'light' || raw === 'dark' || raw === 'system') return raw;
  return 'light';
}

export const theme = ref<ThemePreference>(readStored());

export const systemPrefersDark = ref(
  typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches,
);

export const resolvedTheme = computed<'light' | 'dark'>(() => {
  if (theme.value === 'system') {
    return systemPrefersDark.value ? 'dark' : 'light';
  }
  return theme.value;
});

function applyResolved(resolved: 'light' | 'dark') {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.remove('light', 'dark');
  root.classList.add(resolved);
  root.style.colorScheme = resolved;
}

let themeWatchStarted = false;

/**
 * Call once from `App.vue` (or `ThemeProvider.vue`) so theme reacts to system preference.
 */
export function initThemeRuntime() {
  if (typeof window === 'undefined') return;
  theme.value = readStored();
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  systemPrefersDark.value = mq.matches;
  const onChange = () => {
    systemPrefersDark.value = mq.matches;
  };
  mq.addEventListener('change', onChange);
  if (!themeWatchStarted) {
    themeWatchStarted = true;
    watch(
      resolvedTheme,
      (r) => {
        applyResolved(r);
      },
      { immediate: true },
    );
  }
}

export function useTheme() {
  function setTheme(next: ThemePreference) {
    theme.value = next;
    localStorage.setItem(STORAGE_KEY, next);
    applyResolved(resolvedTheme.value);
  }

  return {
    theme,
    resolvedTheme,
    setTheme,
  };
}
