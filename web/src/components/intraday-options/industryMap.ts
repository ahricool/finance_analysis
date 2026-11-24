import type { IndustryMapMember, IntradayOptionRow } from '@/api/intradayOptions';

interface MapNode {
  id: string;
  label: string;
  change: number | null;
}

interface StockNode extends MapNode {
  kind: 'stock';
  marketCap: number | null;
}

interface BranchNode extends MapNode {
  kind: 'root' | 'sector' | 'industry';
  children: IndustryMapNode[];
  coverage?: { quoted: number; total: number };
}

export type IndustryMapNode = BranchNode | StockNode;

const BENCHMARKS = new Set(['SPY.US', 'QQQ.US']);

function quotedChange(row?: IntradayOptionRow) {
  const change = row?.changePct;
  return row?.quoteStatus === 'ready' && change != null && Number.isFinite(change) ? change : null;
}

function summarize(stocks: StockNode[]) {
  let quoted = 0;
  let sum = 0;
  for (const stock of stocks) {
    if (stock.change === null) continue;
    quoted++;
    sum += stock.change;
  }
  return { change: quoted ? sum / quoted : null, coverage: { quoted, total: stocks.length } };
}

function classificationOrder(left: string | null, right: string | null): number {
  if (left === null) return right === null ? 0 : 1;
  if (right === null) return -1;
  return left.localeCompare(right, 'zh-Hans');
}

export function buildIndustryMap(rows: IntradayOptionRow[], metadata: IndustryMapMember[]) {
  const bySymbol = new Map(metadata.map(member => [member.symbol, member]));
  const sectors = new Map<string | null, Map<string | null, StockNode[]>>();
  let missingCaps = 0;
  for (const row of rows) {
    if (BENCHMARKS.has(row.symbol)) continue;
    const member = bySymbol.get(row.symbol);
    const sector = member?.sector || null;
    const industry = member?.industry || null;
    const marketCap = member?.marketCap ?? null;
    if (marketCap === null) missingCaps++;
    const industries = sectors.get(sector) ?? new Map<string | null, StockNode[]>();
    const stocks = industries.get(industry) ?? [];
    stocks.push({
      kind: 'stock',
      id: row.symbol,
      label: row.symbol.replace(/\.US$/, ''),
      change: quotedChange(row),
      marketCap,
    });
    industries.set(industry, stocks);
    sectors.set(sector, industries);
  }

  const children: BranchNode[] = [...sectors]
    .sort(([left], [right]) => classificationOrder(left, right))
    .map(([sector, industries]) => ({
      kind: 'sector',
      id: JSON.stringify([sector]),
      label: sector ?? '未分类',
      ...summarize([...industries.values()].flat()),
      children: [...industries]
        .sort(([left], [right]) => classificationOrder(left, right))
        .map(([industry, stocks]) => ({
          kind: 'industry',
          id: JSON.stringify([sector, industry]),
          label: industry ?? '未分类',
          ...summarize(stocks),
          children: stocks.sort((left, right) => (right.marketCap ?? 0) - (left.marketCap ?? 0)
            || left.id.localeCompare(right.id)),
        })),
    }));

  const root: BranchNode = {
    kind: 'root',
    id: 'QQQ',
    label: 'QQQ',
    change: quotedChange(rows.find(row => row.symbol === 'QQQ.US')),
    children,
  };
  return { root, missingCaps };
}
