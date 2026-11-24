import type { IndustryMapNode } from './industryMap';

interface PositionedNode {
  node: IndustryMapNode;
  x: number;
  y: number;
  width: number;
}

export function branchIds(node: IndustryMapNode): string[] {
  if (node.kind === 'stock' || !node.children.length) return [];
  return [node.id, ...node.children.flatMap(branchIds)];
}

function makeEdge(parent: PositionedNode, child: PositionedNode, underlineOffset: number) {
  const from = (parent.x + parent.width) * 10;
  const to = child.x * 10;
  const bend = (to - from) * 0.55;
  const fromY = parent.y + underlineOffset;
  const toY = child.y + underlineOffset;
  const change = child.node.change;
  const parentChange = parent.node.change;
  const difference = change == null || parentChange == null ? null : Math.abs(change - parentChange);
  return {
    from: parent.node.id,
    to: child.node.id,
    path: `M ${from} ${fromY} C ${from + bend} ${fromY}, ${to - bend} ${toY}, ${to} ${toY}`,
    direction: change === null || change === 0 ? 'neutral' : change > 0 ? 'up' : 'down',
    width: difference === null ? 1 : 1 + 4 * difference / (difference + 2),
    missing: difference === null,
  };
}

export function layoutIndustryMap(root: IndustryMapNode, collapsed: ReadonlySet<string>, compact: boolean) {
  const columns = compact
    ? [[0, 14], [17, 19], [39, 24], [66, 34]] as const
    : [[0, 14], [20, 16], [45, 20], [73, 27]] as const;
  const rowHeight = compact ? 54 : 36;
  const gaps = compact ? [16, 10, 4] : [22, 11, 5];
  const underlineBottom = 2;
  const underlineOffset = rowHeight / 2 - underlineBottom - 0.5;
  const nodes: PositionedNode[] = [];
  const edges: ReturnType<typeof makeEdge>[] = [];
  let bottom = 0;

  function place(node: IndustryMapNode, level: number): PositionedNode {
    const [x, width] = columns[level]!;
    const position = { node, x, width, y: 0 };
    nodes.push(position);

    if (node.kind === 'stock' || !node.children.length || collapsed.has(node.id)) {
      position.y = bottom + rowHeight / 2;
      bottom += rowHeight;
      return position;
    }

    const children = node.children.map((child, index) => {
      if (index > 0) bottom += gaps[level]!;
      return place(child, level + 1);
    });
    position.y = (children[0]!.y + children[children.length - 1]!.y) / 2;
    edges.push(...children.map(child => makeEdge(position, child, underlineOffset)));
    return position;
  }

  place(root, 0);
  return { nodes, edges, rowHeight, underlineBottom, height: bottom };
}
