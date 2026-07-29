// @vitest-environment node

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const REQUIRED_THEME_TOKENS = [
  '--background', '--foreground', '--card', '--card-foreground', '--popover',
  '--popover-foreground', '--primary', '--primary-foreground', '--secondary',
  '--secondary-foreground', '--muted', '--muted-foreground', '--accent',
  '--accent-foreground', '--destructive', '--destructive-foreground', '--border',
  '--input', '--ring', '--radius', '--market-up', '--market-down', '--success', '--warning',
];

describe('application theme tokens', () => {
  it('defines shadcn and financial tokens in the light theme root block', () => {
    const css = readFileSync(resolve(__dirname, '..', 'src', 'index.css'), 'utf8');
    const rootMatch = css.match(/:root\s*\{([\s\S]*?)\n\}/);

    expect(rootMatch).not.toBeNull();
    const rootBlock = rootMatch?.[1] ?? '';

    for (const token of REQUIRED_THEME_TOKENS) {
      expect(rootBlock).toContain(token);
    }
  });

  it('defines shadcn and financial tokens in the dark theme block', () => {
    const css = readFileSync(resolve(__dirname, '..', 'src', 'index.css'), 'utf8');
    const darkMatch = css.match(/\.dark\s*\{([\s\S]*?)\n\}/);

    expect(darkMatch).not.toBeNull();
    const darkBlock = darkMatch?.[1] ?? '';

    for (const token of REQUIRED_THEME_TOKENS.filter((token) => token !== '--radius')) {
      expect(darkBlock).toContain(token);
    }
  });
});
