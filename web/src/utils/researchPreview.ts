export type ResearchDataMode = 'preview' | 'official';

export const PREVIEW_PROVIDER_LABELS: Record<string, string> = {
  easyquotation_tencent: 'Tencent',
  yfinance: 'Yahoo Finance',
};

export function previewProviderLabel(provider?: string | null): string {
  if (!provider) return '—';
  return PREVIEW_PROVIDER_LABELS[provider] ?? provider;
}

export function isPreviewCompleted(status?: string | null): boolean {
  return status === 'completed';
}

export function compareTradeDate(left?: string | null, right?: string | null): number {
  const a = left?.slice(0, 10) || '';
  const b = right?.slice(0, 10) || '';
  if (a === b) return 0;
  if (!a) return -1;
  if (!b) return 1;
  return a < b ? -1 : 1;
}

export function compareIsoInstant(left?: string | null, right?: string | null): number | null {
  const leftMs = left ? Date.parse(left) : Number.NaN;
  const rightMs = right ? Date.parse(right) : Number.NaN;
  if (!Number.isFinite(leftMs) || !Number.isFinite(rightMs)) return null;
  if (leftMs === rightMs) return 0;
  return leftMs < rightMs ? -1 : 1;
}

export function chooseDefaultResearchDataMode(input: {
  officialTradeDate?: string | null;
  officialGeneratedAt?: string | null;
  previewAvailable: boolean;
  previewStatus?: string | null;
  previewTradeDate?: string | null;
  previewTime?: string | null;
}): ResearchDataMode {
  const previewUsable = input.previewAvailable && isPreviewCompleted(input.previewStatus);
  if (!previewUsable) return 'official';
  if (!input.officialTradeDate) return 'preview';
  const tradeDateOrder = compareTradeDate(input.previewTradeDate, input.officialTradeDate);
  if (tradeDateOrder > 0) return 'preview';
  if (tradeDateOrder < 0) return 'official';
  const generatedOrder = compareIsoInstant(input.officialGeneratedAt, input.previewTime);
  if (generatedOrder == null) return 'preview';
  return generatedOrder >= 0 ? 'official' : 'preview';
}

export interface PreviewChangeItem<T> {
  current: T;
  previous: T | null;
}

export function diffPreviewActionChanges<T extends { code: string; action?: string | null; state?: string | null }>(
  previewItems: T[],
  officialItems: T[],
): {
  newBuys: PreviewChangeItem<T>[];
  newExits: PreviewChangeItem<T>[];
  newEmerging: PreviewChangeItem<T>[];
  newCooling: PreviewChangeItem<T>[];
} {
  const officialByCode = new Map(officialItems.map((item) => [item.code, item]));
  const newBuys: PreviewChangeItem<T>[] = [];
  const newExits: PreviewChangeItem<T>[] = [];
  const newEmerging: PreviewChangeItem<T>[] = [];
  const newCooling: PreviewChangeItem<T>[] = [];
  for (const current of previewItems) {
    const previous = officialByCode.get(current.code) ?? null;
    if (current.action === 'BUY' && previous?.action !== 'BUY') {
      newBuys.push({ current, previous });
    }
    if (current.action === 'EXIT' && previous?.action !== 'EXIT') {
      newExits.push({ current, previous });
    }
    if (current.state === 'EMERGING' && previous?.state !== 'EMERGING') {
      newEmerging.push({ current, previous });
    }
    if (current.state === 'COOLING' && previous?.state !== 'COOLING') {
      newCooling.push({ current, previous });
    }
  }
  return { newBuys, newExits, newEmerging, newCooling };
}

export const TREND_PREVIEW_CANDIDATE_STATES = new Set([
  'CANDIDATE',
  'ENTRY',
  'PYRAMIDING',
  'HOLDING',
  'WEAKENING',
  'REDUCE',
  'EXIT',
]);

export function isTrendPreviewCandidate(item: { state?: string | null; action?: string | null }): boolean {
  return TREND_PREVIEW_CANDIDATE_STATES.has(item.state ?? '') || item.action === 'ADD';
}

export function diffTrendPreviewChanges<T extends { code: string; state?: string | null; action?: string | null }>(
  previewItems: T[],
  officialItems: T[],
): { newCandidates: PreviewChangeItem<T>[]; newExits: PreviewChangeItem<T>[] } {
  const officialByCode = new Map(officialItems.map((item) => [item.code, item]));
  const newCandidates: PreviewChangeItem<T>[] = [];
  const newExits: PreviewChangeItem<T>[] = [];
  for (const current of previewItems) {
    const previous = officialByCode.get(current.code) ?? null;
    if (current.state === 'CANDIDATE' && previous?.state !== 'CANDIDATE') {
      newCandidates.push({ current, previous });
    }
    if (current.action === 'EXIT' && previous?.action !== 'EXIT') {
      newExits.push({ current, previous });
    }
  }
  return { newCandidates, newExits };
}
