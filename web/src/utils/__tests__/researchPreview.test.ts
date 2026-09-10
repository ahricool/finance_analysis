import { describe, expect, it } from 'vitest';
import {
  chooseDefaultResearchDataMode,
  diffPreviewActionChanges,
  isPreviewCompleted,
  isTrendPreviewCandidate,
  previewProviderLabel,
} from '../researchPreview';

describe('researchPreview helpers', () => {
  it('maps internal preview providers to display labels', () => {
    expect(previewProviderLabel('easyquotation_tencent')).toBe('Tencent');
    expect(previewProviderLabel('yfinance')).toBe('Yahoo Finance');
    expect(previewProviderLabel('other')).toBe('other');
  });

  it('defaults to preview when preview trade date is newer', () => {
    expect(chooseDefaultResearchDataMode({
      officialTradeDate: '2026-09-09',
      officialGeneratedAt: '2026-09-09T10:31:00Z',
      previewAvailable: true,
      previewStatus: 'completed',
      previewTradeDate: '2026-09-10',
      previewTime: '2026-09-10T06:35:00Z',
    })).toBe('preview');
  });

  it('defaults to official when the same trade date has a later official snapshot', () => {
    expect(chooseDefaultResearchDataMode({
      officialTradeDate: '2026-09-10',
      officialGeneratedAt: '2026-09-10T10:31:00Z',
      previewAvailable: true,
      previewStatus: 'completed',
      previewTradeDate: '2026-09-10',
      previewTime: '2026-09-10T06:35:00Z',
    })).toBe('official');
  });

  it('ignores incomplete preview payloads when choosing the default mode', () => {
    expect(chooseDefaultResearchDataMode({
      officialTradeDate: '2026-09-09',
      previewAvailable: true,
      previewStatus: 'failed',
      previewTradeDate: '2026-09-10',
      previewTime: '2026-09-10T06:35:00Z',
    })).toBe('official');
    expect(isPreviewCompleted('failed')).toBe(false);
  });

  it('diffs preview BUY/EXIT against official items by code', () => {
    const diff = diffPreviewActionChanges(
      [
        { code: 'A', action: 'BUY', state: 'EMERGING' },
        { code: 'B', action: 'EXIT', state: 'COOLING' },
        { code: 'C', action: 'HOLD', state: 'TRENDING' },
      ],
      [
        { code: 'A', action: 'HOLD', state: 'TRENDING' },
        { code: 'B', action: 'HOLD', state: 'TRENDING' },
        { code: 'C', action: 'HOLD', state: 'TRENDING' },
      ],
    );
    expect(diff.newBuys.map(item => item.current.code)).toEqual(['A']);
    expect(diff.newExits.map(item => item.current.code)).toEqual(['B']);
    expect(diff.newEmerging.map(item => item.current.code)).toEqual(['A']);
    expect(diff.newCooling.map(item => item.current.code)).toEqual(['B']);
  });

  it('treats trend lifecycle states as preview candidates', () => {
    expect(isTrendPreviewCandidate({ state: 'CANDIDATE', action: 'WATCH' })).toBe(true);
    expect(isTrendPreviewCandidate({ state: 'IDLE', action: 'ADD' })).toBe(true);
    expect(isTrendPreviewCandidate({ state: 'IDLE', action: 'WATCH' })).toBe(false);
  });
});
