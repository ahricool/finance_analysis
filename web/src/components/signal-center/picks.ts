import type { SignalDetail, SignalPick, SignalSummary } from '@/api/signalCenter';

export function signalPicks(signal: SignalSummary): SignalPick[] {
  if (signal.recommendations) return signal.recommendations;
  if (signal.decision !== 'BUY' || !signal.selectedSymbol) return [];
  const analysis = (signal as SignalDetail).analysis;
  return [{ symbol: signal.selectedSymbol, name: signal.selectedName, instrumentType: 'STOCK',
    confidence: signal.confidence, thesis: analysis?.thesis || '', positiveSignals: analysis?.positiveSignals || [],
    risks: analysis?.risks || [], invalidations: analysis?.invalidations || [], evidence: [], externalSources: [],
    evaluation: signal.evaluation }];
}

export const noTradeReasons: Record<string, string> = {
  NO_CLEAR_EDGE: '优势不明确', OVERHEATED: '位置过热', SIGNAL_CONFLICT: '信号冲突', INSUFFICIENT_EVIDENCE: '证据不足',
};
export function sourceUrl(value: string): string | undefined {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined; }
  catch { return undefined; }
}
