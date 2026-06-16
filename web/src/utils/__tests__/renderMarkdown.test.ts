import { describe, expect, it } from 'vitest';
import { renderMarkdownToHtml } from '@/utils/renderMarkdown';

describe('renderMarkdownToHtml', () => {
  it('renders markdown and strips script tags', () => {
    const html = renderMarkdownToHtml('# Title\n\n<script>alert(1)</script>\n\n**bold**');
    expect(html).toContain('<h1');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('alert(1)');
  });

  it('returns empty string for blank input', () => {
    expect(renderMarkdownToHtml('')).toBe('');
  });
});
