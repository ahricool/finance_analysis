import { describe, expect, it } from 'vitest';
import { signalPicks, sourceUrl } from '../picks';
import type { SignalSummary } from '@/api/signalCenter';
const legacy: SignalSummary = { market: 'CN', signalDate: '2026-10-29', status: 'completed', selectedSymbol: '600000.SH',
  selectedName: '浦发银行', decision: 'BUY', confidence: 'medium', createdAt: '2026-10-29T12:00:00Z', completedAt: null };
describe('signal compatibility and external sources', () => {
  it('projects legacy BUY but respects an explicitly empty V2 selection', () => {
    expect(signalPicks(legacy).map(p => p.symbol)).toEqual(['600000.SH']);
    expect(signalPicks({ ...legacy, recommendations: [] })).toEqual([]);
    expect(signalPicks({ ...legacy, decision: 'NO_TRADE' })).toEqual([]);
  });
  it('only links HTTP(S) sources without embedded credentials', () => {
    expect(sourceUrl('https://example.com/announcement')).toBe('https://example.com/announcement');
    for (const url of ['javascript:alert(1)', 'data:text/html,hi', 'https://user:password@example.com', 'invalid']) expect(sourceUrl(url)).toBeUndefined();
  });
});
