import { registerOverlay, type OverlayCreate } from 'klinecharts';
import type { TradeMarker } from '@/lib/tradeMarkers';

let registered = false;

export function ensureTradeMarkerOverlay() {
  if (registered) return;
  registered = true;
  registerOverlay<{ label: string; kind: string }>({
    name: 'tradeBst',
    totalStep: 1,
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: ({ coordinates, overlay }) => {
      const point = coordinates[0];
      if (!point) return [];
      const { label, kind } = overlay.extendData as { label: string; kind: string };
      const color = kind === 'B' ? '#dc2626' : kind === 'S' ? '#16854e' : '#2563eb';
      return [{
        type: 'text',
        attrs: { x: point.x, y: point.y - 18, text: label, align: 'center', baseline: 'middle' },
        styles: { color, size: 12, weight: 'bold', backgroundColor: '#ffffff', paddingLeft: 3, paddingRight: 3 },
      }];
    },
  });
}

export function tradeMarkerOverlays(
  markers: TradeMarker[],
  priceOf: (timestamp: number) => number,
  onSelect?: (marker: TradeMarker) => void,
): OverlayCreate[] {
  ensureTradeMarkerOverlay();
  return markers.map((marker, index) => ({
    name: 'tradeBst',
    id: `bst-${marker.timestamp}-${index}`,
    groupId: 'strategy-markers',
    lock: true,
    points: [{ timestamp: marker.timestamp, value: priceOf(marker.timestamp) }],
    extendData: { label: marker.type, kind: marker.type },
    onClick: () => {
      onSelect?.(marker);
      return true;
    },
  }));
}
