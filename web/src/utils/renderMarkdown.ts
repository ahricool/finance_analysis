import DOMPurify from 'dompurify';
import { marked } from 'marked';

/**
 * Parse Markdown to sanitized HTML safe for v-html rendering.
 */
export function renderMarkdownToHtml(markdown: string): string {
  if (!markdown) return '';
  try {
    const raw = marked.parse(markdown, { async: false, gfm: true }) as string;
    return wrapScrollableMarkdownBlocks(DOMPurify.sanitize(raw));
  } catch {
    return '';
  }
}

function wrapScrollableMarkdownBlocks(html: string): string {
  if (typeof document === 'undefined') return html;

  const template = document.createElement('template');
  template.innerHTML = html;

  for (const element of Array.from(template.content.querySelectorAll('table, pre'))) {
    const parent = element.parentElement;
    if (parent?.classList.contains('markdown-horizontal-scroll')) continue;

    const wrapper = document.createElement('div');
    wrapper.className = 'markdown-horizontal-scroll';
    wrapper.setAttribute('data-scroll-area', 'horizontal');
    wrapper.setAttribute('tabindex', '0');
    wrapper.setAttribute(
      'aria-label',
      element.tagName === 'TABLE' ? 'Markdown 表格横向滚动区域' : 'Markdown 代码块横向滚动区域',
    );

    element.parentNode?.insertBefore(wrapper, element);
    wrapper.appendChild(element);
  }

  return template.innerHTML;
}
