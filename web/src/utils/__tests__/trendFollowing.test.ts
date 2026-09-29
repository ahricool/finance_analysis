import { expect, it } from 'vitest';
import { alphaVersionLabel } from '../trendFollowing';

it.each([[3, 'V3'], [4, 'V4'], [null, '—'], [undefined, '—']] as const)(
  'formats Alpha version %s as %s', (version, expected) => {
    expect(alphaVersionLabel(version)).toBe(expected);
  },
);
