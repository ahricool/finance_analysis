import DOMPurify from 'dompurify';
import { marked } from 'marked';

function wrapWideTables(html: string): string {
  if (!html.includes('<table')) return html;

  return html.replace(/<table\b[^>]*>[\s\S]*?<\/table>/gi, (tableHtml) => {
    return `<div class="table-scroll-x table-scroll-x-inline">${tableHtml}</div>`;
  });
}

/**
 * Parse Markdown to sanitized HTML safe for v-html rendering.
 */
export function renderMarkdownToHtml(markdown: string): string {
  if (!markdown) return '';
  try {
    const raw = marked.parse(markdown, { async: false, gfm: true }) as string;
    return wrapWideTables(DOMPurify.sanitize(raw));
  } catch {
    return '';
  }
}
