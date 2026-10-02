/**
 * Resolve theme CSS custom properties to concrete colors for canvas / chart libs
 * that cannot consume `hsl(var(--token))` directly.
 */
function readHslVar(name: string, fallback: string): string {
  if (typeof window === 'undefined' || typeof document === 'undefined') return fallback;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!raw) return fallback;
  return raw.includes('hsl') ? raw : `hsl(${raw})`;
}

/** A-share market tones: up=red, down=green. */
export function readMarketCanvasColors(dark = false): {
  up: string;
  down: string;
  muted: string;
} {
  return {
    up: readHslVar('--market-up', dark ? '#e86464' : '#dc2626'),
    down: readHslVar('--market-down', dark ? '#39b77a' : '#16854e'),
    muted: readHslVar('--muted-foreground', '#888888'),
  };
}

/** Hex fallbacks matching current light/dark tokens (for overlays without DOM). */
export const MARKET_HEX = {
  light: { up: '#dc2626', down: '#16854e' },
  dark: { up: '#e86464', down: '#39b77a' },
} as const;
