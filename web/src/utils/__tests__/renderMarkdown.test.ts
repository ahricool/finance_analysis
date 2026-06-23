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

  it('wraps markdown tables and code blocks in local horizontal scroll areas', () => {
    const html = renderMarkdownToHtml('| A | B |\n| --- | --- |\n| 1 | 2 |\n\n```txt\nvery long code\n```');

    expect(html).toContain('class="markdown-horizontal-scroll"');
    expect(html).toContain('data-scroll-area="horizontal"');
    expect(html).toContain('aria-label="Markdown 表格横向滚动区域"');
    expect(html).toContain('aria-label="Markdown 代码块横向滚动区域"');
    expect(html).toContain('<table>');
    expect(html).toContain('<pre>');
  });
});
