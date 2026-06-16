import DOMPurify from 'dompurify';
import { marked } from 'marked';

/**
 * Parse Markdown to sanitized HTML safe for v-html rendering.
 */
export function renderMarkdownToHtml(markdown: string): string {
  if (!markdown) return '';
  try {
    const raw = marked.parse(markdown, { async: false, gfm: true }) as string;
    return DOMPurify.sanitize(raw);
  } catch {
    return '';
  }
}
