import { describe, expect, it } from 'vitest';
import {
  directionDotClass,
  directionSurfaceClass,
  directionTextClass,
  signedTextClass,
  signedTone,
} from '../marketTone';

describe('marketTone', () => {
  it('maps signed values to A-share up/down tones', () => {
    expect(signedTone(1.2)).toBe('up');
    expect(signedTone(-0.5)).toBe('down');
    expect(signedTone(0)).toBe('flat');
    expect(signedTone(null)).toBe('flat');
    expect(signedTextClass(3)).toBe('text-market-up');
    expect(signedTextClass(-3)).toBe('text-market-down');
    expect(signedTextClass(0)).toBe('text-muted-foreground');
  });

  it('maps directional labels to market colors', () => {
    expect(directionTextClass('bullish')).toBe('text-market-up');
    expect(directionTextClass('bearish')).toBe('text-market-down');
    expect(directionDotClass('above')).toBe('bg-market-up');
    expect(directionDotClass('below')).toBe('bg-market-down');
    expect(directionDotClass('neutral')).toBe('bg-warning');
    expect(directionSurfaceClass('bullish', 'strong')).toContain('market-up');
    expect(directionSurfaceClass('bearish', 'soft')).toContain('market-down');
  });
});
