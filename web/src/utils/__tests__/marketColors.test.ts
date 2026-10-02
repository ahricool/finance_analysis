import { describe, expect, it, vi, afterEach } from 'vitest';
import { MARKET_HEX, readMarketCanvasColors } from '../marketColors';

describe('marketColors', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('exposes stable hex fallbacks for light and dark', () => {
    expect(MARKET_HEX.light.up).toMatch(/^#/);
    expect(MARKET_HEX.dark.down).toMatch(/^#/);
  });

  it('reads CSS variables when document is available', () => {
    const getPropertyValue = vi.fn((name: string) => {
      if (name === '--market-up') return '0 72% 52%';
      if (name === '--market-down') return '152 60% 38%';
      if (name === '--muted-foreground') return '0 0% 45%';
      return '';
    });
    vi.stubGlobal('window', {});
    vi.stubGlobal('document', {
      documentElement: {},
    });
    vi.stubGlobal('getComputedStyle', () => ({ getPropertyValue }));
    const colors = readMarketCanvasColors(false);
    expect(colors.up).toBe('hsl(0 72% 52%)');
    expect(colors.down).toBe('hsl(152 60% 38%)');
    expect(getPropertyValue).toHaveBeenCalled();
  });
});
