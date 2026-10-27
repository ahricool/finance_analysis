/**
 * Shared numeric display helpers. Missing or non-finite values always render as
 * the fallback (default "—"), never as 0/NaN, and `signed` only prefixes "+" on
 * strictly positive values so zero stays unsigned.
 */
export type NumberFormatOptions = {
  digits?: number;
  signed?: boolean;
  fallback?: string;
};

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function sign(value: number, signed: boolean) {
  return signed && value > 0 ? '+' : '';
}

/** Fixed decimals, e.g. scores and ratios. */
export function formatFixed(value: unknown, { digits = 2, signed = false, fallback = '—' }: NumberFormatOptions = {}): string {
  if (!isFiniteNumber(value)) return fallback;
  return `${sign(value, signed)}${value.toFixed(digits)}`;
}

/** Ratio rendered as percent: 0.123 → "12.3%". */
export function formatPercent(value: unknown, { digits = 1, signed = false, fallback = '—' }: NumberFormatOptions = {}): string {
  if (!isFiniteNumber(value)) return fallback;
  return `${sign(value, signed)}${(value * 100).toFixed(digits)}%`;
}
