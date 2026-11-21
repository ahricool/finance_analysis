import { registerOverlay } from 'klinecharts';
import type { IntradayBar } from '@/api/intradayMarket';
import type { SimTrade, SimulationSnapshot } from '@/api/intradayOptions';
import { markerWidth, type ChartAnnotation } from '@/components/market-data/chartAnnotation';
import { MARKET_HEX } from '@/utils/marketColors';
import { confirmationLabel, opportunityKinds } from './labels';

export interface SimulationOperation {
  id: string; tradeId: string; action: 'B' | 'S'; phase: 'entry' | 'exit'; label: string;
  at: string; processedAt: string; priceAt: string | undefined; price: number;
  estimated: boolean; reason: string;
}
export interface SimulationMarker {
  timestamp: number; label: string; action: 'B' | 'S' | 'B/S'; anchor: number; operations: SimulationOperation[];
}
const marketDay = (timestamp: number) => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(timestamp);

/** Durable trade rows win over entry-only event copies; reconnect replay cannot duplicate markers. */
export function simulationOperations(snapshot: SimulationSnapshot | null | undefined, symbol: string, day: string): SimulationOperation[] {
  const trades = new Map<string, SimTrade>();
  const copies = [
    ...(snapshot?.events ?? []).flatMap(e => e.trade ? [e.trade] : []),
    ...(snapshot?.states ?? []).flatMap(s => s.position ? [s.position] : []),
    ...(snapshot?.trades ?? []),
  ];
  for (const trade of copies) {
    if (trade.symbol !== symbol || ![1, -1].includes(trade.side)) continue;
    if (!trades.get(trade.id)?.exitAt || trade.exitAt) trades.set(trade.id, trade);
  }
  return [...trades.values()].flatMap(t => {
    const operations: SimulationOperation[] = [];
    const append = (phase: 'entry' | 'exit', at: string | undefined, price: number | undefined) => {
      const timestamp = Date.parse(at ?? '');
      if (!Number.isFinite(timestamp) || marketDay(timestamp) !== day || price == null || !Number.isFinite(price) || price <= 0) return;
      const buy = (phase === 'entry') === (t.side === 1);
      operations.push({
        id: `${t.id}:${phase}`, tradeId: t.id, action: buy ? 'B' : 'S', phase,
        label: `模拟${t.side === 1 ? '做多' : '做空'}${phase === 'entry' ? '进场' : '退场'}`,
        at: at!, processedAt: phase === 'entry' ? t.entryAt : t.exitAt!,
        priceAt: phase === 'entry' ? t.entryPriceAt : t.exitPriceAt,
        price, estimated: phase === 'exit' && !!t.estimated,
        reason: phase === 'entry' ? [opportunityKinds[t.kind], t.confirmationMethod ? confirmationLabel(t.confirmationMethod) : null,
          '合格机会自动模拟进场'].filter(Boolean).join(' · ') : [t.exitReason, t.estimated ? t.anomaly : null].filter(Boolean).join('；'),
      });
    };
    append('entry', t.entryAt, t.entryPrice);
    if (t.exitAt) append('exit', t.estimated ? t.plannedExitAt : t.exitAt, t.exitPrice);
    return operations;
  }).sort((a, b) => Date.parse(a.at) - Date.parse(b.at) || a.id.localeCompare(b.id));
}

/** Execution timestamps belong to [minute start, minute end), including the live candle. */
export function simulationMarkers(operations: SimulationOperation[], bars: IntradayBar[]): SimulationMarker[] {
  const available = new Map(bars.map(b => [b.timestamp, b]));
  const groups = new Map<number, SimulationOperation[]>();
  for (const operation of operations) {
    const minute = Math.floor(Date.parse(operation.at) / 60_000) * 60_000;
    if (!available.has(minute)) continue; // Never move a trade to a neighbouring candle across a gap.
    groups.set(minute, [...(groups.get(minute) ?? []), operation]);
  }
  return [...groups].map(([timestamp, rows]) => {
    const sides = new Set(rows.map(r => r.action));
    const action = sides.size > 1 ? 'B/S' : rows[0]!.action;
    return { timestamp, action, label: `${action}${rows.some(r => r.estimated) ? '*' : ''}`,
      anchor: action === 'B' ? available.get(timestamp)!.low : available.get(timestamp)!.high, operations: rows };
  });
}

let registered = false;
export function simulationTradeOverlays(markers: SimulationMarker[], dark: boolean, select: (timestamp: number) => void): ChartAnnotation[] {
  if (!registered) {
    registerOverlay<{ marker: SimulationMarker; dark: boolean }>({
      name: 'intradaySimulationTrade', totalStep: 1, needDefaultPointFigure: false,
      needDefaultXAxisFigure: false, needDefaultYAxisFigure: false,
      createPointFigures: ({ chart, coordinates, overlay, bounding }) => {
        const point = coordinates[0];
        if (!point || point.y < 0 || point.y > bounding.height) return [];
        const { marker, dark } = overlay.extendData;
        const palette = dark ? MARKET_HEX.dark : MARKET_HEX.light;
        const size = Math.max(15, markerWidth(chart) * 1.4);
        const y = point.y + (marker.action === 'B' ? 1 : -1) * (size / 2 + 5);
        return [{ type: 'text', ignoreEvent: ['onRightClick'], attrs: { x: point.x,
          y: Math.min(bounding.height - size / 2, Math.max(size / 2, y)),
          text: marker.label, align: 'center', baseline: 'middle' }, styles: { size, weight: 'bold',
          color: marker.action === 'B' ? palette.up : marker.action === 'S' ? palette.down : '#a855f7',
          backgroundColor: dark ? '#171717' : '#ffffff', borderSize: 0, paddingLeft: 1, paddingRight: 1, paddingTop: 0, paddingBottom: 0 } }];
      },
    });
    registered = true;
  }
  return markers.map(marker => ({ name: 'intradaySimulationTrade', id: `simulation-trade-${marker.timestamp}`,
    groupId: 'intraday-simulation-trades', lock: true, fixedZLevel: true, zLevel: 5,
    hint: `${marker.label} · ${[...new Set(marker.operations.map(op => op.label))].join('、')}${marker.label.endsWith('*') ? '（含估算退场）' : ''}，点击查看记录`,
    points: [{ timestamp: marker.timestamp, value: marker.anchor }], extendData: { marker, dark },
    onClick: () => { select(marker.timestamp); return true; },
  }));
}
