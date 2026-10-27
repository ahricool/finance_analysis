import type { Router } from 'vue-router';

// A deploy replaces every hashed chunk in static/, so a tab opened before it
// can no longer lazy-load routes. Reload once into the target URL instead of
// leaving navigation silently broken.
const RELOAD_KEY = 'fa:chunk-reload';
const RELOAD_COOLDOWN_MS = 10_000;
const CHUNK_ERROR_PATTERN = /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Unable to preload CSS/i;

export function isChunkLoadError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : typeof error === 'string' ? error : '';
  return CHUNK_ERROR_PATTERN.test(message);
}

function readLastReload(): { url: string; at: number } | null {
  try {
    const raw = sessionStorage.getItem(RELOAD_KEY);
    return raw ? JSON.parse(raw) as { url: string; at: number } : null;
  } catch {
    return null;
  }
}

/** Returns false when the same URL was already reloaded recently, so a truly missing chunk cannot loop. */
export function reloadForStaleChunk(url: string, now = Date.now()): boolean {
  const last = readLastReload();
  if (last?.url === url && now - last.at < RELOAD_COOLDOWN_MS) return false;
  try {
    sessionStorage.setItem(RELOAD_KEY, JSON.stringify({ url, at: now }));
  } catch {
    // Without storage the cooldown is unavailable; one reload attempt is still safer than a dead route.
  }
  window.location.assign(url);
  return true;
}

/** Route chunks (and their preloaded CSS) reject into router.onError; other lazy imports keep their own error UI. */
export function installChunkReload(router: Router) {
  router.onError((error, to) => {
    if (isChunkLoadError(error)) reloadForStaleChunk(router.resolve(to).href);
  });
}
