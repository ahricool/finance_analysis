// @vitest-environment node

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('index.html theme bootstrap', () => {
  it('preloads a system-first theme before Vue mounts and respects stored light/dark values', () => {
    const indexHtml = readFileSync(resolve(__dirname, '..', 'index.html'), 'utf8');

    expect(indexHtml).toContain("const storageKey = 'theme'");
    expect(indexHtml).toContain("storedTheme === 'light' || storedTheme === 'dark'");
    expect(indexHtml).toContain("window.matchMedia('(prefers-color-scheme: dark)').matches");
    expect(indexHtml).not.toContain("? storedTheme : 'light'");
    expect(indexHtml).toContain("root.classList.remove('light', 'dark');");
    expect(indexHtml).toContain('root.classList.add(resolved);');
    expect(indexHtml).toContain('root.style.colorScheme = resolved;');
  });
});
