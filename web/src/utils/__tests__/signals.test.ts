import { describe, expect, it } from 'vitest';
import {
  directionLabel,
  evaluationState,
  evaluationStatusLabel,
  formatReturnPct,
  signalTypeLabel,
} from '../signals';

describe('signal display utilities', () => {
  it('labels every supported direction', () => {
    expect(directionLabel('bullish')).toBe('看多');
    expect(directionLabel('bearish')).toBe('看空');
    expect(directionLabel('sideways')).toBe('震荡');
    expect(directionLabel('neutral')).toBe('中性');
  });

  it('distinguishes evaluated, pending, not applicable, and malformed periods', () => {
    const evaluation = {
      '30m': { returnPct: 1.25 },
      '1h': { status: 'not_applicable' as const },
      '3d': {},
    };
    expect(evaluationState(evaluation, '30m')).toBe('evaluated');
    expect(evaluationStatusLabel(evaluation, '30m')).toBe('+1.25%');
    expect(evaluationState(evaluation, '1h')).toBe('not_applicable');
    expect(evaluationStatusLabel(evaluation, '1h')).toBe('不适用');
    expect(evaluationState(evaluation, '1d')).toBe('pending');
    expect(evaluationStatusLabel(evaluation, '1d')).toBe('待评估');
    expect(evaluationState(evaluation, '3d')).toBe('invalid');
    expect(evaluationStatusLabel(evaluation, '3d')).toBe('—');
  });

  it('formats signed returns and falls back to raw unknown signal types', () => {
    expect(formatReturnPct(-0.82)).toBe('-0.82%');
    expect(formatReturnPct(0)).toBe('0.00%');
    expect(signalTypeLabel('weak_to_strong_reversal')).toBe('弱转强');
    expect(signalTypeLabel('custom_signal')).toBe('custom_signal');
  });
});
