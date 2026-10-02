/**
 * Shared market / semantic tone classes for A-share convention:
 * up = red (--market-up), down = green (--market-down).
 * Prefer these helpers over raw Tailwind red/emerald utilities.
 */

export type SignedTone = 'up' | 'down' | 'flat';

export function signedTone(value: number | null | undefined): SignedTone {
  if (value == null || !Number.isFinite(value) || value === 0) return 'flat';
  return value > 0 ? 'up' : 'down';
}

/** Text color for signed numeric change (pct / PnL / return). */
export function signedTextClass(value: number | null | undefined): string {
  const tone = signedTone(value);
  if (tone === 'up') return 'text-market-up';
  if (tone === 'down') return 'text-market-down';
  return 'text-muted-foreground';
}

/** Bullish / bearish directional text (trend, pattern, impact). */
export function directionTextClass(direction: 'bullish' | 'bearish' | 'neutral' | string | null | undefined): string {
  if (direction === 'bullish' || direction === 'up' || direction === 'above' || direction === 'CALL') {
    return 'text-market-up';
  }
  if (direction === 'bearish' || direction === 'down' || direction === 'below' || direction === 'PUT') {
    return 'text-market-down';
  }
  return 'text-muted-foreground';
}

export function directionDotClass(direction: 'bullish' | 'bearish' | 'neutral' | 'above' | 'below' | string | null | undefined): string {
  if (direction === 'bullish' || direction === 'up' || direction === 'above') return 'bg-market-up';
  if (direction === 'bearish' || direction === 'down' || direction === 'below') return 'bg-market-down';
  if (direction === 'neutral') return 'bg-warning';
  return 'bg-muted-foreground';
}

/** Soft badge/chip surfaces for bullish / bearish callouts. */
export function directionSurfaceClass(
  direction: 'bullish' | 'bearish' | 'neutral' | string,
  intensity: 'strong' | 'medium' | 'soft' = 'medium',
): string {
  if (direction === 'bullish') {
    if (intensity === 'strong') return 'border-market-up/35 bg-market-up/12 text-market-up';
    if (intensity === 'soft') return 'border-market-up/20 bg-market-up/5 text-market-up/80';
    return 'border-market-up/25 bg-market-up/7 text-market-up';
  }
  if (direction === 'bearish') {
    if (intensity === 'strong') return 'border-market-down/35 bg-market-down/12 text-market-down';
    if (intensity === 'soft') return 'border-market-down/20 bg-market-down/5 text-market-down/80';
    return 'border-market-down/25 bg-market-down/7 text-market-down';
  }
  return 'border-border bg-muted text-muted-foreground';
}
