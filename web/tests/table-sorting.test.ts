import { readFileSync, readdirSync } from 'node:fs';
import { resolve, relative } from 'node:path';
import { parse as parseTemplate, NodeTypes, type ElementNode, type TemplateChildNode, type RootNode } from '@vue/compiler-dom';
import { parse } from '@vue/compiler-sfc';
import { describe, expect, it } from 'vitest';

const root = resolve(__dirname, '..', 'src');
function files(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = resolve(directory, entry.name);
    return entry.isDirectory() ? files(path) : path.endsWith('.vue') ? [path] : [];
  });
}
function elements(node: RootNode | ElementNode): ElementNode[] {
  return node.children.flatMap((child: TemplateChildNode) => child.type === NodeTypes.ELEMENT ? [child, ...elements(child)] : []);
}
const backendPaged: Record<string, string> = {
  'pages/NotificationsPage.vue:0': 'Notification history uses backend page/size.',
  'pages/TasksPage.vue:1': 'Task runs use backend page/size.',
  'pages/market/SignalCenterPage.vue:0': 'Signal history uses backend offsets.',
  'components/market-sentiment/PoolTable.vue:0': 'Sentiment pools use backend page/size.',
  'components/trend-following/TrendEventStudy.vue:2': 'Event details use backend offsets.',
};

describe('application table sorting policy', () => {
  it('makes every local data column sortable, exempting only backend pages, actions and column groups', () => {
    const violations: string[] = [];
    const seenExceptions = new Set<string>();
    for (const file of files(root).filter(path => !path.includes('/components/ui/'))) {
      const source = readFileSync(file, 'utf8');
      const template = parse(source).descriptor.template?.content;
      if (!template) continue;
      const nodes = elements(parseTemplate(template));
      const tables = nodes.filter(node => node.tag === 'Table' || node.tag === 'table');
      tables.forEach((table, index) => {
        const key = `${relative(root, file)}:${index}`;
        if (backendPaged[key]) { seenExceptions.add(key); return; }
        const headers = elements(table).filter(node => node.tag === 'thead' || node.tag === 'TableHeader')
          .flatMap(section => elements(section).filter(node => node.tag === 'th' || node.tag === 'TableHead'));
        for (const header of headers) {
          const text = header.loc.source;
          if (text.includes('操作') || header.props.some(prop => prop.name === 'colspan' || (prop.type === NodeTypes.DIRECTIVE && prop.arg?.type === NodeTypes.SIMPLE_EXPRESSION && prop.arg.content === 'colspan'))) continue;
          const interactive = elements(header).some(node => node.tag === 'button' && node.props.some(prop => prop.type === NodeTypes.DIRECTIVE && prop.name === 'on' && prop.arg?.type === NodeTypes.SIMPLE_EXPRESSION && prop.arg.content === 'click'));
          if (!interactive) violations.push(`${key}: ${text.replace(/\s+/g, ' ').slice(0, 180)}`);
        }
        if (!elements(table).some(node => node.tag === 'SortableTableHeader' || (node.tag === 'button' && node.loc.source.includes('@click')))) violations.push(`${key}: missing sortable headers`);
      });
    }
    expect(violations).toEqual([]);
    expect([...seenExceptions].sort()).toEqual(Object.keys(backendPaged).sort());
  });
});
