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

  it('wraps markdown tables in a horizontal scroll container', () => {
    const html = renderMarkdownToHtml('| A | B |\n| --- | --- |\n| 1 | 2 |');
    expect(html).toContain('class="table-scroll-x table-scroll-x-inline"');
    expect(html).toContain('<table');
  });
});
