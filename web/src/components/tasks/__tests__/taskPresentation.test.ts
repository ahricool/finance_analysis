import { describe, expect, it } from 'vitest';
import { DEFAULT_RUN_STATUS_FILTERS, isRunBusy, runStatusLabel, runStatusVariant } from '../taskPresentation';

describe('partial business task outcome', () => {
  it('shows a terminal warning and remains visible in default filters', () => {
    expect(runStatusLabel('partial')).toBe('部分失败');
    expect(runStatusVariant('partial')).toBe('warning');
    expect(isRunBusy('partial')).toBe(false);
    expect(DEFAULT_RUN_STATUS_FILTERS).toContain('partial');
  });
});
