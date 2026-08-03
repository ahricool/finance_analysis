import { describe, expect, it } from 'vitest';
import { formatSecurityLabel } from '@/utils/security';

describe('formatSecurityLabel', () => {
  it('renders code and name using the shared display contract', () => {
    expect(formatSecurityLabel('600519.SH', '贵州茅台')).toBe('600519.SH - 贵州茅台');
    expect(formatSecurityLabel('AAPL.US', 'Apple Inc.')).toBe('AAPL.US - Apple Inc.');
  });

  it('falls back without duplicated or dangling separators', () => {
    expect(formatSecurityLabel('AAPL.US', null)).toBe('AAPL.US');
    expect(formatSecurityLabel('AAPL.US', 'aapl.us')).toBe('AAPL.US');
    expect(formatSecurityLabel('', '')).toBe('—');
  });
});
